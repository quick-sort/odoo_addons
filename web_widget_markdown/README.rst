===================
Web Widget Markdown
===================

A Markdown field widget for Odoo 19 form views.

It renders a ``Text`` (or ``Char``) field as a markdown source editor with an
**Edit / Preview** toggle: edit in a plain monospace textarea, then preview the
rendered HTML. In read-only mode the field is always rendered.

Features
--------

* Lightweight: only the MIT-licensed ``marked`` parser is vendored; the rendered
  HTML is sanitized with Odoo's bundled DOMPurify before display.
* Edit mode: a monospace textarea for the markdown source.
* Preview mode: the markdown rendered as HTML with basic typography.
* Read-only mode: always renders the markdown to HTML.

Usage
-----

.. code-block:: xml

    <field name="body" widget="markdown"/>

The underlying field is a ``fields.Text`` holding the markdown source.

Dependencies
------------

* ``web``

See ``docs/`` for requirements, design and acceptance criteria.
