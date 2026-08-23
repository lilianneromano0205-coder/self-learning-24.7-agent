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
USER agent

ENV PYTHONUNBUFFERED=1 PYTHONUTF8=1
EXPOSE 7777

# prove the build before it ever serves: the suite must pass inside the image
RUN python tests/run_all.py

# the control panel; expert loops are started from it (or run loop.py directly)
CMD ["python", "ui.py", "--host", "0.0.0.0", "--port", "7777"]
