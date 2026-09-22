from odoo.tests import common, tagged

from ..services.semantics import accumulate_stream, strip_think


@tagged("post_install", "-at_install")
class TestStripThink(common.TransactionCase):
    def test_strips_single_think_block(self):
        visible, think = strip_think("<think>reasoning</think>answer")
        self.assertEqual(visible, "answer")
        self.assertEqual(think, ["<think>reasoning</think>"])

    def test_strips_multiple_think_blocks(self):
        visible, think = strip_think("<think>a</think>x<think>b</think>y")
        self.assertEqual(visible, "xy")
        self.assertEqual(len(think), 2)

    def test_no_think_block(self):
        visible, think = strip_think("plain answer")
        self.assertEqual(visible, "plain answer")
        self.assertEqual(think, [])

    def test_multiline_think_block(self):
        visible, _ = strip_think("<think>line1\nline2</think>\nresult")
        self.assertEqual(visible, "result")


@tagged("post_install", "-at_install")
class TestAccumulateStream(common.TransactionCase):
    def test_accumulates_and_finishes(self):
        frames = [
            {"content": "Hel", "finish": False},
            {"content": "lo", "finish": False},
            {"content": " world", "finish": True},
        ]
        text, finished = accumulate_stream(frames)
        self.assertEqual(text, "Hello world")
        self.assertTrue(finished)

    def test_not_finished_without_finish_flag(self):
        text, finished = accumulate_stream([{"content": "partial", "finish": False}])
        self.assertEqual(text, "partial")
        self.assertFalse(finished)
