# Ultroid - UserBot
# Copyright (C) 2021-2026 TeamUltroid
# This file is a part of < https://github.com/TeamUltroid/Ultroid/ >
# PLease read the GNU Affero General Public License in <https://www.github.com/TeamUltroid/Ultroid/blob/main/LICENSE/>.

FROM theteamultroid/ultroid:main

# set timezone
ENV TZ=Asia/Kolkata
RUN ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone

# Install against BoudyOS' checked-out dependency manifests. The base image supplies
# the system packages, but its bundled TeamUltroid checkout is not our runtime source.
COPY requirements.txt /tmp/boudyos/requirements.txt
COPY resources/startup/optional-requirements.txt /tmp/boudyos/optional-requirements.txt
RUN python3 -m pip install --no-cache-dir \
        -r /tmp/boudyos/requirements.txt \
        -r /tmp/boudyos/optional-requirements.txt \
    && rm -rf /tmp/boudyos /root/TeamUltroid

# Keep the historical path for scripts and deployment configuration that rely on it.
WORKDIR "/root/TeamUltroid"

# Copy the current BoudyOS checkout only after dependency setup so every deployment
# runs this source tree (including its bundled brand assets).
COPY . .

# Runtime update checks expect a Git checkout. Recreate metadata without copying
# host credentials or other .git state into the image, and track the BoudyOS fork.
RUN git init -b main \
    && git remote add origin https://github.com/boudywho/BoudyOS.git \
    && git fetch --depth=1 origin main \
    && git reset --mixed origin/main \
    && git branch --set-upstream-to=origin/main main

CMD ["bash", "startup"]
