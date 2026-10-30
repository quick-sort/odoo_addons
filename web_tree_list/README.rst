Tree List View
==============

An enhanced list view that renders a **recursive multi-level collapsible tree**
when the list is grouped by a self-referencing ``many2one`` field (e.g.
``parent_id``).

Standard Odoo ``group_by`` on such a field produces only one flat level of group
headers. This view rebuilds the parent/child hierarchy and lets you expand and
collapse each level.

Usage
-----

Declare a list view with ``js_class="tree_list"`` on a model that has a
self-referencing ``many2one`` field::

    <list js_class="tree_list" default_group_by="parent_id" default_order="sequence, name">
        <field name="name"/>
    </list>

The tree mode activates automatically when the active ``group_by`` is a single
self-referencing ``many2one``. When not grouped by such a field, the view
behaves exactly like a normal list view (edit toggle, filters, sorting, and
other group-by fields all keep working).

See `docs/` for requirements, design and acceptance criteria.
