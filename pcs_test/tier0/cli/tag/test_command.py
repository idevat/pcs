from textwrap import dedent
from unittest import mock, TestCase

from pcs.cli.common.errors import CmdLineInputError
from pcs.cli.tag import command
from pcs.lib.errors import LibraryError
from pcs_test.tools.misc import dict_to_modifiers


class TagCreate(TestCase):
    def setUp(self):
        self.lib = mock.Mock(spec_set=["tag"])
        self.tag = mock.Mock(spec_set=["create"])
        self.lib.tag = self.tag

    def _call_cmd(self, argv):
        command.tag_create(self.lib, argv, dict_to_modifiers({}))

    def test_no_args(self):
        with self.assertRaises(CmdLineInputError) as cm:
            self._call_cmd([])
        self.assertIsNone(cm.exception.message)
        self.tag.create.assert_not_called()

    def test_not_enough_args(self):
        with self.assertRaises(CmdLineInputError) as cm:
            self._call_cmd(["arg1"])
        self.assertIsNone(cm.exception.message)
        self.tag.create.assert_not_called()

    def test_minimum_args(self):
        self._call_cmd(["arg1", "arg2"])
        self.tag.create.assert_called_once_with("arg1", ["arg2"])

    def test_empty_args(self):
        self._call_cmd(["", ""])
        self.tag.create.assert_called_once_with("", [""])

    def test_multiple_args(self):
        self._call_cmd(["tagid", "id1", "id2"])
        self.tag.create.assert_called_once_with("tagid", ["id1", "id2"])


@mock.patch("pcs.cli.tag.command.print")
class TagConfig(TestCase):
    tag_dicts = [
        {
            "tag_id": "tag1",
            "idref_list": ["i1", "i2", "i3"],
        },
        {
            "tag_id": "tag2",
            "idref_list": ["j1", "j2", "j3"],
        },
    ]

    def setUp(self):
        self.lib = mock.Mock(spec_set=["tag"])
        self.tag = mock.Mock(spec_set=["config"])
        self.lib.tag = self.tag

    def _call_cmd(self, argv):
        command.tag_config(self.lib, argv, dict_to_modifiers({}))

    def test_no_args_no_tags(self, mock_print):
        self.tag.config.return_value = []
        self._call_cmd([])
        self.tag.config.assert_called_once_with([])
        mock_print.assert_called_once_with(" No tags defined")

    def test_no_args_all_tags(self, mock_print):
        self.tag.config.return_value = self.tag_dicts
        self._call_cmd([])
        self.tag.config.assert_called_once_with([])
        mock_print.assert_called_once_with(
            dedent(
                """\
            tag1
              i1
              i2
              i3
            tag2
              j1
              j2
              j3"""
            )
        )

    def test_specified_tag(self, mock_print):
        self.tag.config.return_value = self.tag_dicts[1:2]
        self._call_cmd(["tag2"])
        self.tag.config.assert_called_once_with(["tag2"])
        mock_print.assert_called_once_with(
            dedent(
                """\
            tag2
              j1
              j2
              j3"""
            )
        )

    def test_specified_another_tag(self, mock_print):
        self.tag.config.return_value = self.tag_dicts[0:1]
        self._call_cmd(["tag1"])
        self.tag.config.assert_called_once_with(["tag1"])
        mock_print.assert_called_once_with(
            dedent(
                """\
            tag1
              i1
              i2
              i3"""
            )
        )

    def test_specified_more_tags_are_printed_in_given_order(self, mock_print):
        self.tag.config.return_value = self.tag_dicts[::-1]
        self._call_cmd(["tag2", "tag1"])
        self.tag.config.assert_called_once_with(["tag2", "tag1"])
        mock_print.assert_called_once_with(
            dedent(
                """\
            tag2
              j1
              j2
              j3
            tag1
              i1
              i2
              i3"""
            )
        )

    def test_no_print_on_exception(self, mock_print):
        self.tag.config.side_effect = LibraryError()
        with self.assertRaises(LibraryError):
            self._call_cmd(["something"])
        self.tag.config.assert_called_once_with(["something"])
        mock_print.assert_not_called()


class TagRemove(TestCase):
    def setUp(self):
        self.lib = mock.Mock(spec_set=["tag"])
        self.tag = mock.Mock(spec_set=["remove"])
        self.lib.tag = self.tag

    def _call_cmd(self, argv):
        command.tag_remove(self.lib, argv, dict_to_modifiers({}))

    def test_no_args(self):
        with self.assertRaises(CmdLineInputError) as cm:
            self._call_cmd([])
        self.assertIsNone(cm.exception.message)
        self.tag.remove.assert_not_called()

    def test_minimum_args(self):
        self._call_cmd(["arg1"])
        self.tag.remove.assert_called_once_with(["arg1"])

    def test_more_args(self):
        self._call_cmd(["arg1", "arg2"])
        self.tag.remove.assert_called_once_with(["arg1", "arg2"])


class TagUpdate(TestCase):
    def setUp(self):
        self.lib = mock.Mock(spec_set=["tag"])
        self.tag = mock.Mock(spec_set=["update"])
        self.lib.tag = self.tag

    def _call_cmd(self, argv, options=None):
        if options is None:
            options = {}
        command.tag_update(self.lib, argv, dict_to_modifiers(options))

    def assert_exception_hint(self, argv):
        with self.assertRaises(CmdLineInputError) as cm:
            self._call_cmd(argv)
        self.assertEqual(
            cm.exception.hint,
            "Specify at least one id for 'add' or 'remove' arguments.",
        )
        self.tag.update.assert_not_called()

    def test_no_args(self):
        with self.assertRaises(CmdLineInputError) as cm:
            self._call_cmd([])
        self.assertIsNone(cm.exception.message)
        self.tag.update.assert_not_called()

    def test_no_add_remove_keywords(self):
        self.assert_exception_hint(["tag_id"])

    def test_add_without_ids(self):
        self.assert_exception_hint(["tag_id", "add"])

    def test_remove_without_ids(self):
        self.assert_exception_hint(["tag_id", "remove"])

    def test_add_remove_without_ids(self):
        self.assert_exception_hint(["tag_id", "add", "remove"])

    def test_add_and_empty_remove(self):
        self.assert_exception_hint(["tag_id", "add", "id1", "remove"])

    def test_remove_and_empty_add(self):
        self.assert_exception_hint(["tag_id", "add", "remove", "id1"])

    def test_both_after_and_before(self):
        with self.assertRaises(CmdLineInputError) as cm:
            self._call_cmd(
                ["tag_id", "add", "id1"],
                dict(after="A", before="B"),
            )
        self.assertEqual(
            cm.exception.message, "Cannot specify both --before and --after"
        )
        self.tag.update.assert_not_called()

    def test_only_add(self):
        self._call_cmd(["tag_id", "add", "id1"])
        self.tag.update.assert_called_once_with(
            "tag_id",
            ["id1"],
            [],
            adjacent_idref=None,
            put_after_adjacent=True,
        )

    def test_only_remove(self):
        self._call_cmd(["tag_id", "remove", "id1"])
        self.tag.update.assert_called_once_with(
            "tag_id",
            [],
            ["id1"],
            adjacent_idref=None,
            put_after_adjacent=True,
        )

    def test_both_add_remove(self):
        self._call_cmd(["tag_id", "remove", "i", "j", "add", "k", "l"])
        self.tag.update.assert_called_once_with(
            "tag_id",
            ["k", "l"],
            ["i", "j"],
            adjacent_idref=None,
            put_after_adjacent=True,
        )

    def test_only_add_after(self):
        self._call_cmd(["tag_id", "add", "id1"], dict(after="A"))
        self.tag.update.assert_called_once_with(
            "tag_id",
            ["id1"],
            [],
            adjacent_idref="A",
            put_after_adjacent=True,
        )

    def test_only_add_before(self):
        self._call_cmd(["tag_id", "add", "id1"], dict(before="B"))
        self.tag.update.assert_called_once_with(
            "tag_id",
            ["id1"],
            [],
            adjacent_idref="B",
            put_after_adjacent=False,
        )

    def test_add_after_and_remove(self):
        self._call_cmd(
            ["tag_id", "add", "id1", "id2", "remove", "id3", "id4"],
            dict(after="A"),
        )
        self.tag.update.assert_called_once_with(
            "tag_id",
            ["id1", "id2"],
            ["id3", "id4"],
            adjacent_idref="A",
            put_after_adjacent=True,
        )

    def test_add_before_and_remove(self):
        self._call_cmd(
            ["tag_id", "add", "id1", "id2", "remove", "id3", "id4"],
            dict(before="B"),
        )
        self.tag.update.assert_called_once_with(
            "tag_id",
            ["id1", "id2"],
            ["id3", "id4"],
            adjacent_idref="B",
            put_after_adjacent=False,
        )
