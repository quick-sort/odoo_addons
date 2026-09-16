# Odoo 19 with this addons repository baked in.
#
# Python dependencies are deliberately NOT installed here. Each addon carries
# its own requirements.txt, so a deployment installs only what the addons it
# actually uses require:
#
#     pip install -r /mnt/extra-addons/odoo_addons/infohub_channel_rss/requirements.txt
#
# or, in a derived image:
#
#     FROM odoo-addons:19.0
#     USER root
#     RUN pip3 install --no-cache-dir --break-system-packages \
#             -r /mnt/extra-addons/odoo_addons/llm/requirements.txt
#
# Odoo does not read requirements.txt -- it checks `external_dependencies` in
# each __manifest__.py. The files are generated from those manifests by
# scripts/generate_requirements.py, so the two stay in step.

FROM odoo:19.0-20260908

# The base image already declares /mnt/extra-addons as a VOLUME and sets it as
# the default addons_path. Writing here means the addons are found with no
# config change. Note that a VOLUME is seeded from the image on first use, so
# the contents below persist into an anonymous volume but are shadowed by any
# bind mount -- mount the repository at this path to override it at runtime.
COPY --chown=odoo:odoo . /mnt/extra-addons/odoo_addons

# `legacy/` holds the retired three-axis implementation. It is kept for
# reference and is inert: Odoo scans addons_path with a non-recursive listdir,
# and `legacy/` has no __manifest__.py at its root, so none of it is loadable.
# It is shipped because it costs a few hundred kilobytes and losing the
# reference material is worse than carrying it.

# Nothing to install, so no `USER root` section. The image runs as `odoo`.
# Verify with:
#     docker build -t odoo-addons:19.0 .
#     docker run --rm odoo-addons:19.0 python3 -c \
#         "import odoo; print(odoo.release.version)"
