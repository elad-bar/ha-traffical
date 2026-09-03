# Linux test environment for the full pytest suite.
#
# Native Windows Python has no `fcntl`, so `tests/conftest.py` skips the Home
# Assistant plugin tests. This image matches CI (Debian, Python 3.13) so nothing
# is skipped. Debian rather than the Alpine HA base image on purpose: that image
# resolves wheels through Home Assistant's musllinux index, which fails TLS
# verification behind a network doing certificate inspection.
FROM python:3.13

ENV PIP_ROOT_USER_ACTION=ignore \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /repo

# Only the requirements are copied so the dependency layer stays cached; the
# repo itself is bind-mounted at run time.
COPY requirements.txt requirements-dev.txt ./
RUN pip install --no-cache-dir -r requirements.txt -r requirements-dev.txt

CMD ["python", "-m", "pytest", "-q", "-p", "no:cacheprovider"]
