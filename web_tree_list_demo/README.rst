Tree List View Demo
===================

Demo addon for ``web_tree_list``. It defines a self-referencing ``category``
model and a list view using ``js_class="tree_list"`` with
``default_group_by="parent_id"`` so the recursive tree renders immediately on
opening the menu.

To verify:

1. Install ``web_tree_list_demo`` (pulls in ``web_tree_list``).
2. Open menu **Tree List Demo**.
3. The list groups by ``parent_id`` and shows the 3-level demo tree with
   collapsible group headers per level.
