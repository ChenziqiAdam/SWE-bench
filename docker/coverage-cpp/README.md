# C++ coverage evaluator

Build and publish this image before an offline experiment:

```bash
podman build \
  -t localhost/swebench-coverage-cpp:gcc12.5-cmake3.25-gcovr8.6 \
  docker/coverage-cpp
```

The runtime starts with networking disabled, the host UID/GID, all capabilities
dropped, and only the checkout and result directory mounted.
