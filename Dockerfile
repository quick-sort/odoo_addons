# Odoo 19 with this addons repository baked in.
#
# Python dependencies are installed from each addon's requirements.txt (generated
# from __manifest__.py by scripts/generate_requirements.py). The default build
# installs nothing -- pass the addon list you actually use:
#
#     docker build --build-arg INSTALL_ADDONS="llm llm_openai infohub" .
#
# docker-compose.yml carries the production list as a build arg. Odoo does not
# read requirements.txt itself; it checks `external_dependencies` in each
# __manifest__.py, and the two are kept in step by the generator script.

FROM odoo:19.0-20260908

# The base image declares /mnt/extra-addons as a VOLUME. Copying the addons
# there would rely on anonymous-volume seeding: every container recreate leaves
# an orphan volume behind. /opt/odoo_addons is plain image content -- a rebuilt
# image always ships the current code, with no volume lifecycle to manage.
# odoo.conf lists it in addons_path. Leave /mnt/extra-addons (empty, from the
# base image) available for ad-hoc mounted addons.
COPY --chown=odoo:odoo . /opt/odoo_addons

ARG PIP_INDEX_URL=https://mirrors.tuna.tsinghua.edu.cn/pypi/web/simple/
ARG INSTALL_ADDONS=""
USER root
# --target into a dedicated dir (same approach as .github/workflows/test.yml):
# Debian-managed packages (typing_extensions et al.) have no pip RECORD file,
# so upgrading them in place fails. pip-installed cryptography/cffi are removed
# afterwards to keep the image's pyOpenSSL pairing intact.
RUN set -e; \
    for a in $INSTALL_ADDONS; do \
        if [ -f /opt/odoo_addons/$a/requirements.txt ]; then \
            pip3 install --no-cache-dir --target /opt/python-deps \
                -r /opt/odoo_addons/$a/requirements.txt; \
        fi; \
    done; \
    rm -rf /opt/python-deps/cryptography* /opt/python-deps/cffi*
ENV PYTHONPATH=/opt/python-deps
USER odoo

# The base image ships python3; curl availability is not guaranteed.
# start-period covers a long first boot (database + module installation).
HEALTHCHECK --interval=30s --timeout=10s --start-period=5m --retries=3 \
    CMD python3 -c "import urllib.request as u; u.urlopen('http://127.0.0.1:8069/web/health', timeout=5)"

# Verify with:
#     docker build -t odoo-addons:19.0 .
#     docker run --rm odoo-addons:19.0 python3 -c \
#         "import odoo; print(odoo.release.version)"
