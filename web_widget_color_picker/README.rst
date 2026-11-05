=======================
Web Widget Color Picker
=======================

A compact color-index field widget for Odoo 19 form and list views.

``compact_color_picker`` renders an ``Integer`` field holding a standard Odoo
color index (0–11) as a single color dot. Clicking the dot opens the palette;
picking a color writes the new value immediately.

Usage
-----

.. code-block:: xml

    <field name="color_index" widget="compact_color_picker"/>

* Works in forms and editable lists.
* Collapses to the current color instead of showing the whole palette.
* Saves on selection, so list cells persist without entering edit mode.
* Read-only fields cannot be expanded.

Dependencies
------------

* ``web``

See ``docs/`` for requirements, design and acceptance criteria.
