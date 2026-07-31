# Ultroid - UserBot
# Copyright (C) 2021-2026 TeamUltroid
# This file is a part of < https://github.com/TeamUltroid/Ultroid/ >
# PLease read the GNU Affero General Public License in <https://www.github.com/TeamUltroid/Ultroid/blob/main/LICENSE/>.

FROM python:3.13-slim-bookworm

ARG BOUDYOS_SOURCE_COMMIT=unknown
ARG BOUDYOS_SOURCE_TAG=untagged
ARG BOUDYOS_SOURCE_DIRTY=1
LABEL org.opencontainers.image.source="https://github.com/boudywho/BoudyOS" \
      org.opencontainers.image.version="${BOUDYOS_SOURCE_TAG}" \
      org.opencontainers.image.revision="${BOUDYOS_SOURCE_COMMIT}"

# set timezone
ENV TZ=Asia/Kolkata
RUN ln -snf /usr/share/zoneinfo/$TZ /etc/localtime \
    && echo $TZ > /etc/timezone \
    && apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates ffmpeg git mediainfo wkhtmltopdf \
    && rm -rf /var/lib/apt/lists/*

# Install against BoudyOS' checked-out dependency manifests. The base image supplies
# the system packages, but its bundled TeamUltroid checkout is not our runtime source.
COPY requirements.txt /tmp/boudyos/requirements.txt
COPY requirements /tmp/boudyos/requirements
COPY constraints /tmp/boudyos/constraints
RUN python3 -m pip install --no-cache-dir \
        -r /tmp/boudyos/requirements/media.txt \
        -c /tmp/boudyos/constraints/py313.txt \
    && python3 -m pip check \
    && rm -rf /tmp/boudyos

# Keep the historical path for scripts and deployment configuration that rely on it.
WORKDIR "/root/TeamUltroid"

# Copy the current BoudyOS checkout only after dependency setup so every deployment
# runs this source tree (including its bundled brand assets).
COPY . .

# The image never fabricates Git metadata for remote main. CI/release builders
# pass the exact clean context identity; local/default builds remain explicitly
# unverified and Git-based updater semantics stay disabled.
RUN printf '%s\n' \
    "{\"schema_version\":1,\"origin\":\"https://github.com/boudywho/BoudyOS.git\",\"tag\":\"${BOUDYOS_SOURCE_TAG}\",\"commit\":\"${BOUDYOS_SOURCE_COMMIT}\",\"dirty\":${BOUDYOS_SOURCE_DIRTY}}" \
    > /opt/boudyos-release.json
ENV BOUDYOS_RELEASE_METADATA=/opt/boudyos-release.json

CMD ["bash", "startup"]
