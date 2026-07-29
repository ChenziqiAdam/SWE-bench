FROM gcc:12.5.0-bookworm@sha256:98c8b0d34f13e8f6c74a8e88b0adf0d5611354bf029fd83e25bbcd830d5feb3a

ARG CMAKE_VERSION=3.25.1-1
ARG NINJA_VERSION=1.11.1-2~deb12u1
ARG PYTHON_VERSION=3.11.2-1+b1
ARG GCOVR_VERSION=8.6

RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      "cmake=${CMAKE_VERSION}" \
      "ninja-build=${NINJA_VERSION}" \
      "python3=${PYTHON_VERSION}" \
      python3-pip \
 && python3 -m pip install --no-cache-dir --break-system-packages "gcovr==${GCOVR_VERSION}" \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /workspace
