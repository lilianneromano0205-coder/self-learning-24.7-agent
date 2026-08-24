# The sandbox: the agent runs shell commands a model chose, so give it a box
# it cannot leave. Build and run:
#
#   docker build -t expert-fleet .
#   docker run -d --name fleet \
#     --env-file agent.env \
#     -v fleet-data:/home/agent/agent/experts \
#     -p 127.0.0.1:7777:7777 \
#     --memory 2g --pids-limit 512 \
#     expert-fleet
#
# Only the experts/ volume persists — code is immutable inside the image, and
# nothing on your host filesystem is reachable from the container.
#
# On Cloudflare Containers there is no volume to mount, because *"all disk is
# ephemeral"* (CLOUDFLARE.md §3.2). The image therefore ships an entrypoint
# that restores from R2 at boot and snapshots back to it on an interval and on
# SIGTERM. R2 is reached with backup.py push/pull and is NEVER mounted: this
# platform's concurrency correctness rests on O_EXCL and atomic rename, and
# neither holds on object storage. deploy/README.md is the operator's manual
# for that, including the data-loss window between snapshots.

FROM python:3.12-slim

# ingestion tools; everything else is stdlib
RUN apt-get update && apt-get install -y --no-install-recommends \
        ffmpeg pandoc curl ca-certificates \
    && pip install --no-cache-dir pymupdf yt-dlp markitdown \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

# unprivileged user — a confused `rm -rf` should cost a container, not a host
RUN useradd --create-home --shell /usr/sbin/nologin agent
WORKDIR /home/agent/agent
COPY --chown=agent:agent . /home/agent/agent
RUN mkdir -p experts inbox courses logs contexts skills \
    && chown -R agent:agent /home/agent/agent

# The entrypoint is authored on a Windows machine. A CRLF line ending after
# `#!/bin/sh` makes the kernel look for an interpreter called "/bin/sh\r" and
# report "no such file or directory" for a file that is plainly right there —
# an error that sends people hunting for the wrong bug. .gitattributes pins
# eol=lf for the repository; this strips them again for anyone who exported
# the tree some other way. Also: COPY does not preserve the executable bit
# from a filesystem that has no concept of one.
RUN sed -i 's/\r$//' deploy/entrypoint.sh \
    && chmod 0755 deploy/entrypoint.sh \
    && chown agent:agent deploy/entrypoint.sh

# A state directory that is NOT the code directory, for deployments that want
# archives to carry only the fleet's mind: set FLEET_HOME=/home/agent/fleet and
# every snapshot is state alone, with the code coming from this image. It is
# created but not made the default, because docker-compose.yml mounts its
# volume at /home/agent/agent/experts and changing the default underneath it
# would silently move the fleet off that volume.
RUN mkdir -p /home/agent/fleet && chown agent:agent /home/agent/fleet

USER agent

ENV PYTHONUNBUFFERED=1 PYTHONUTF8=1
EXPOSE 7777

# prove the build before it ever serves: the suite must pass inside the image
RUN python tests/run_all.py

# Restore, run, snapshot. With no arguments the entrypoint runs FLEET_MODE:
# `serve` (the default) starts the control panel on 0.0.0.0:7777 exactly as
# the previous CMD did, so docker-compose.yml keeps working unchanged; `drain`
# empties every expert's queue and exits, which is what a Durable Object alarm
# wants (CLOUDFLARE.md §6.4).
#
# There is deliberately no CMD. A CMD would arrive as arguments, and arguments
# REPLACE the workload — a fixed CMD would therefore make FLEET_MODE dead
# configuration that quietly does nothing. To run something else once, with
# the same restore/snapshot lifecycle around it:
#
#   docker run --rm --env-file agent.env expert-fleet python doctor.py
#
ENTRYPOINT ["/home/agent/agent/deploy/entrypoint.sh"]
