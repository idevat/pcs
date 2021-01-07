import re
from textwrap import dedent
from unittest import TestCase

from pcs.cli import nvset
from pcs.common.pacemaker.nvset import (
    CibNvpairDto,
    CibNvsetDto,
)
from pcs.common.pacemaker.rule import CibRuleExpressionDto
from pcs.common.types import (
    CibNvsetType,
    CibRuleInEffectStatus,
    CibRuleExpressionType,
)


type_to_label = (
    (CibNvsetType.META, "Meta Attrs"),
    (CibNvsetType.INSTANCE, "Attributes"),
)


class NvsetDtoToLines(TestCase):
    @staticmethod
    def _export(dto, with_ids):
        return (
            "\n".join(nvset.nvset_dto_to_lines(dto, with_ids=with_ids)) + "\n"
        )

    def assert_lines(self, dto, lines):
        self.assertEqual(
            self._export(dto, True),
            lines,
        )
        self.assertEqual(
            self._export(dto, False),
            re.sub(r" +\(id:.*\)", "", lines),
        )

    def test_minimal(self):
        for nvtype, label in type_to_label:
            with self.subTest(nvset_type=nvtype, label=label):
                dto = CibNvsetDto("my-id", nvtype, {}, None, [])
                output = dedent(
                    f"""\
                      {label}: my-id
                    """
                )
                self.assert_lines(dto, output)

    def test_full(self):
        for nvtype, label in type_to_label:
            with self.subTest(nvset_type=nvtype, label=label):
                dto = CibNvsetDto(
                    "my-id",
                    nvtype,
                    {"score": "150"},
                    CibRuleExpressionDto(
                        "my-id-rule",
                        CibRuleExpressionType.RULE,
                        CibRuleInEffectStatus.UNKNOWN,
                        {"boolean-op": "or"},
                        None,
                        None,
                        [
                            CibRuleExpressionDto(
                                "my-id-rule-op",
                                CibRuleExpressionType.OP_EXPRESSION,
                                CibRuleInEffectStatus.UNKNOWN,
                                {"name": "monitor"},
                                None,
                                None,
                                [],
                                "op monitor",
                            ),
                        ],
                        "op monitor",
                    ),
                    [
                        CibNvpairDto("my-id-pair1", "name1", "value1"),
                        CibNvpairDto("my-id-pair2", "name 2", "value 2"),
                        CibNvpairDto("my-id-pair3", "name=3", "value=3"),
                    ],
                )
                output = dedent(
                    f"""\
                    {label}: my-id score=150
                      "name 2"="value 2"
                      name1=value1
                      "name=3"="value=3"
                      Rule: boolean-op=or (id:my-id-rule)
                        Expression: op monitor (id:my-id-rule-op)
                    """
                )
                self.assert_lines(dto, output)


class NvsetDtoListToLines(TestCase):
    @staticmethod
    def _export(dto, with_ids, include_expired):
        return (
            "\n".join(
                nvset.nvset_dto_list_to_lines(
                    dto, with_ids=with_ids, include_expired=include_expired
                )
            )
            + "\n"
        )

    def assert_lines(self, dto, include_expired, lines):
        self.assertEqual(
            self._export(dto, True, include_expired),
            lines,
        )
        self.assertEqual(
            self._export(dto, False, include_expired),
            re.sub(r" +\(id:.*\)", "", lines),
        )

    @staticmethod
    def fixture_dto(nvtype, in_effect):
        return CibNvsetDto(
            f"id-{in_effect}",
            nvtype,
            {"score": "150"},
            CibRuleExpressionDto(
                f"id-{in_effect}-rule",
                CibRuleExpressionType.RULE,
                in_effect,
                {"boolean-op": "or"},
                None,
                None,
                [
                    CibRuleExpressionDto(
                        f"id-{in_effect}-rule-op",
                        CibRuleExpressionType.OP_EXPRESSION,
                        CibRuleInEffectStatus.UNKNOWN,
                        {"name": "monitor"},
                        None,
                        None,
                        [],
                        "op monitor",
                    ),
                ],
                "op monitor",
            ),
            [CibNvpairDto(f"id-{in_effect}-pair1", "name1", "value1")],
        )

    def fixture_dto_list(self, nvtype):
        return [
            self.fixture_dto(nvtype, in_effect)
            for in_effect in CibRuleInEffectStatus
        ]

    def test_expired_included(self):
        self.maxDiff = None
        for nvtype, label in type_to_label:
            with self.subTest(nvset_type=nvtype, label=label):
                output = dedent(
                    f"""\
                    {label} (not yet in effect): id-NOT_YET_IN_EFFECT score=150
                      name1=value1
                      Rule (not yet in effect): boolean-op=or (id:id-NOT_YET_IN_EFFECT-rule)
                        Expression: op monitor (id:id-NOT_YET_IN_EFFECT-rule-op)
                    {label}: id-IN_EFFECT score=150
                      name1=value1
                      Rule: boolean-op=or (id:id-IN_EFFECT-rule)
                        Expression: op monitor (id:id-IN_EFFECT-rule-op)
                    {label} (expired): id-EXPIRED score=150
                      name1=value1
                      Rule (expired): boolean-op=or (id:id-EXPIRED-rule)
                        Expression: op monitor (id:id-EXPIRED-rule-op)
                    {label}: id-UNKNOWN score=150
                      name1=value1
                      Rule: boolean-op=or (id:id-UNKNOWN-rule)
                        Expression: op monitor (id:id-UNKNOWN-rule-op)
                """
                )
                self.assert_lines(self.fixture_dto_list(nvtype), True, output)

    def test_expired_excluded(self):
        self.maxDiff = None
        for nvtype, label in type_to_label:
            with self.subTest(nvset_type=nvtype, label=label):
                output = dedent(
                    f"""\
                    {label} (not yet in effect): id-NOT_YET_IN_EFFECT score=150
                      name1=value1
                      Rule (not yet in effect): boolean-op=or (id:id-NOT_YET_IN_EFFECT-rule)
                        Expression: op monitor (id:id-NOT_YET_IN_EFFECT-rule-op)
                    {label}: id-IN_EFFECT score=150
                      name1=value1
                      Rule: boolean-op=or (id:id-IN_EFFECT-rule)
                        Expression: op monitor (id:id-IN_EFFECT-rule-op)
                    {label}: id-UNKNOWN score=150
                      name1=value1
                      Rule: boolean-op=or (id:id-UNKNOWN-rule)
                        Expression: op monitor (id:id-UNKNOWN-rule-op)
                """
                )
                self.assert_lines(self.fixture_dto_list(nvtype), False, output)
