"""Single-turn, read-only CLI and evaluation runner for NPC Response v0.1."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv  # noqa: E402

from llm import LLMProviderClient, LLMProviderError, create_llm_client  # noqa: E402
from npc.context_builder import build_npc_context  # noqa: E402
from npc.response_runtime import (  # noqa: E402
    NpcInteractionUnavailableError,
    NpcResponseError,
    generate_npc_response,
    load_response_prompt,
    load_response_schema,
)
from scripts.inspect_npc_context import load_world_state  # noqa: E402


TEST_CASES_PATH = PROJECT_ROOT / "data" / "npc_response_test_cases.json"
SEED_PATH = PROJECT_ROOT / "data" / "world_seed.json"
SAVE_PATH = PROJECT_ROOT / "data" / "saves" / "current_world.json"
PROFILES_PATH = PROJECT_ROOT / "data" / "npcs" / "anchor_npcs.json"


class GuardProvider:
    """Fail immediately if a deterministic no-LLM Case crosses the boundary."""

    provider = "guard"
    model = "no-call"

    def __init__(self) -> None:
        self.calls = 0

    def create_structured_output(self, **_: Any) -> str:
        self.calls += 1
        raise AssertionError("LLM must not be called for this Evaluation Case.")


def configure_console_encoding() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            reconfigure(encoding="utf-8")


def file_hash(path: Path) -> str | None:
    if not path.exists():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_player_utterance() -> str:
    print("What do you say? Submit an empty line to finish:")
    lines: list[str] = []
    while True:
        try:
            line = input()
        except EOFError:
            break
        if not line.strip():
            break
        lines.append(line)
    utterance = "\n".join(lines).strip()
    if not utterance:
        raise NpcResponseError("Player utterance must not be empty.")
    return utterance


def load_test_cases(case_number: int | None = None) -> list[dict[str, Any]]:
    try:
        document = json.loads(TEST_CASES_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise NpcResponseError("NPC Response Evaluation data is not valid JSON.") from exc
    cases = document.get("cases") if isinstance(document, dict) else None
    if not isinstance(cases, list) or len(cases) != 8:
        raise NpcResponseError("NPC Response Evaluation requires exactly 8 cases.")
    if case_number is None:
        return cases
    expected_id = f"case_{case_number}"
    selected = [case for case in cases if case.get("id") == expected_id]
    if len(selected) != 1:
        raise NpcResponseError(f"NPC Response Evaluation Case {case_number} is missing.")
    return selected


def normalize_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value).casefold().replace("_", " ")).strip()


def contains_any(text: str, patterns: tuple[str, ...]) -> bool:
    normalized = normalize_text(text)
    return any(normalize_text(pattern) in normalized for pattern in patterns)


def is_primarily_chinese(text: str) -> bool:
    """Allow proper names while rejecting a predominantly English response."""

    han_count = len(re.findall(r"[\u4e00-\u9fff]", text))
    latin_count = len(re.findall(r"[A-Za-z]", text))
    return han_count >= 4 and han_count >= latin_count


def nested_keys(value: Any) -> set[str]:
    keys: set[str] = set()
    if isinstance(value, dict):
        for key, child in value.items():
            keys.add(key)
            keys.update(nested_keys(child))
    elif isinstance(value, list):
        for child in value:
            keys.update(nested_keys(child))
    return keys


def evaluate_expected_behavior(
    case_id: str,
    response: dict[str, Any],
) -> list[str]:
    failures: list[str] = []
    speech = response.get("speech", "")
    references = response.get("referenced_knowledge", {})
    entity_ids = references.get("entity_ids", [])
    facts = references.get("facts", [])

    def require(condition: bool, message: str) -> None:
        if not condition:
            failures.append(message)

    ignorance_patterns = ("不知道", "不清楚", "不确定", "没听说", "无法确定", "不了解")

    if case_id == "case_1":
        require(response.get("knowledge_status") == "known", "knowledge_status should be known")
        require("npc_bjorn" in entity_ids, "referenced_knowledge should include npc_bjorn")
        require(contains_any(speech, ("铁匠", "blacksmith")), "speech should identify Bjorn as a blacksmith")
        require(
            not contains_any(speech, ("gruff", "proud", "reliable", "心里", "秘密目标")),
            "speech should not reveal Bjorn private Profile information",
        )
    elif case_id == "case_2":
        require(response.get("knowledge_status") in {"unknown", "partial"}, "knowledge should be unknown or partial")
        require(contains_any(speech, ignorance_patterns), "speech should admit uncertainty")
        require("npc_haldor" not in entity_ids, "Haldor must not be cited as known Context knowledge")
    elif case_id == "case_3":
        require(
            response.get("knowledge_status") in {"not_applicable", "partial"},
            "a personal aspiration should not be presented as established factual knowledge",
        )
        personality_signals = (
            "好奇",
            "想知道",
            "想看看",
            "看看",
            "探索",
            "发现",
            "见识",
            "外面",
            "世界",
            "哪里",
            "去哪",
            "打算",
            "计划",
            "准备",
            "小心",
            "路线",
            "安全",
            "补给",
            "自己决定",
            "靠自己",
            "curious",
            "discovery",
            "practical",
            "independent",
            "self-reliance",
        )
        require(
            contains_any(speech, personality_signals),
            "speech should express at least one context-relevant Astrid personality, value, or goal signal",
        )
        require(
            not contains_any(
                speech,
                (
                    "我对外面的世界毫无兴趣",
                    "我一点也不好奇",
                    "外面的世界没意思",
                    "你不许自己决定",
                ),
            ),
            "speech should not clearly contradict Astrid's established personality or values",
        )
        require(
            not contains_any(
                speech,
                (
                    "我去过 Skeld 外面",
                    "我去过Skeld外面",
                    "我知道外面一定有",
                    "Skeld 外面肯定有",
                    "Skeld外面肯定有",
                ),
            ),
            "speech should not invent an unsupported World Fact about places beyond Skeld",
        )
        require(
            {
                "relationship_delta",
                "memory_write",
                "quest_update",
                "state_mutations",
                "proposed_mutations",
            }.isdisjoint(nested_keys(response)),
            "response must contain no mutation fields",
        )
    elif case_id == "case_4":
        require(response.get("response_type") == "disagreement", "response_type should be disagreement")
        require(response.get("knowledge_status") == "known", "knowledge_status should be known")
        require("npc_bjorn" in entity_ids, "referenced_knowledge should include npc_bjorn")
        require(contains_any(speech, ("铁匠", "blacksmith")), "speech should preserve Bjorn's blacksmith identity")
        require(contains_any(speech, ("不是", "不对", "哪来的", "没这回事")), "speech should reject the Player claim")
    elif case_id == "case_5":
        require(response.get("knowledge_status") in {"unknown", "partial"}, "private fear should be unknown")
        require(contains_any(speech, ignorance_patterns), "speech should not invent private psychology")
    elif case_id == "case_6":
        require(response.get("knowledge_status") == "known", "coastal activity should be known")
        require(
            is_primarily_chinese(speech),
            "a Chinese Player utterance should receive a primarily Chinese response",
        )
        require(
            "recent strange activity near the coast" in facts,
            "response should reference the exact known coastal fact",
        )
        require(
            contains_any(speech, ("海边", "海岸", "沿海", "coast", "shore"))
            and contains_any(
                speech,
                (
                    "奇怪",
                    "异常",
                    "不寻常",
                    "古怪",
                    "反常",
                    "不对劲",
                    "动静",
                    "strange activity",
                    "unusual activity",
                    "odd activity",
                ),
            ),
            "speech should semantically mention recent unusual activity near the coast",
        )
        require(
            "npc_bjorn" not in entity_ids,
            "npc_bjorn should not be referenced without a Context-supported link to the coastal fact",
        )
        require(
            not contains_any(
                speech,
                (
                    "全村人都在讨论",
                    "村里人都在讨论",
                    "大家都在谈",
                    "人人都知道",
                    "Bjorn 告诉",
                    "Bjorn告诉",
                    "Bjorn 说",
                    "Bjorn说",
                    "从 Bjorn 那里听说",
                    "从Bjorn那里听说",
                    "everyone around Skeld",
                    "the whole village",
                    "Bjorn told",
                    "heard from Bjorn",
                    "我听说",
                    "听人说",
                    "有人告诉我",
                    "听来的",
                    "凶手",
                    "怪物袭击",
                    "海龙袭击",
                    "船被毁",
                    "尸体",
                    "有人失踪",
                    "神秘脚印",
                ),
            ),
            "speech should not invent a source, audience, cause, actor, consequence, or specific event",
        )
    elif case_id == "case_7":
        require(
            response.get("response_type") in {"reaction", "refusal", "disagreement", "question"},
            "response should be a social reaction rather than a factual answer",
        )
        require(response.get("knowledge_status") == "not_applicable", "knowledge_status should be not_applicable")
        forbidden = {
            "relationship_delta",
            "memory_write",
            "quest_update",
            "state_mutations",
            "proposed_mutations",
        }
        require(forbidden.isdisjoint(nested_keys(response)), "response must contain no mutation fields")
    else:
        failures.append(f"no LLM semantic checks are defined for {case_id}")
    return failures


def build_case_world(
    world_state: dict[str, Any],
    test_case: dict[str, Any],
) -> dict[str, Any]:
    case_world = copy.deepcopy(world_state)
    setup = test_case.get("setup")
    if isinstance(setup, dict) and "player_current_location" in setup:
        location_id = setup["player_current_location"]
        if location_id not in case_world.get("locations", {}):
            raise NpcResponseError(f"Evaluation setup references unknown Location: {location_id}")
        case_world["player"]["current_location"] = location_id
    return case_world


def run_test_mode(
    world_state: dict[str, Any],
    test_case_number: int | None = None,
) -> int:
    cases = load_test_cases(test_case_number)
    hashes_before = {
        SEED_PATH: file_hash(SEED_PATH),
        SAVE_PATH: file_hash(SAVE_PATH),
        PROFILES_PATH: file_hash(PROFILES_PATH),
    }
    provider_client: LLMProviderClient | None = None
    system_prompt: str | None = None
    response_schema: dict[str, Any] | None = None
    passed = 0

    try:
        for test_case in cases:
            case_id = str(test_case.get("id", "unknown_case"))
            npc_id = test_case.get("npc_id")
            utterance = test_case.get("player_utterance")
            print(f"\n=== {case_id} ===")
            print(f"npc: {npc_id}")
            print(f"player: {utterance}")
            if not isinstance(npc_id, str) or not isinstance(utterance, str):
                print("Result: FAIL - invalid Evaluation data")
                continue

            case_world = build_case_world(world_state, test_case)
            if case_id == "case_8":
                guard_provider = GuardProvider()
                try:
                    generate_npc_response(
                        npc_id,
                        utterance,
                        case_world,
                        provider_client=guard_provider,  # type: ignore[arg-type]
                    )
                    print("Result: FAIL - interaction should have been unavailable")
                except NpcInteractionUnavailableError as exc:
                    if guard_provider.calls == 0:
                        print(f"Deterministic precondition: PASS - {exc}")
                        print("LLM call count: 0")
                        print("Result: PASS")
                        passed += 1
                    else:
                        print("Result: FAIL - LLM was called before co-location rejection")
                continue

            if provider_client is None:
                provider_client = create_llm_client()
                system_prompt = load_response_prompt()
                response_schema = load_response_schema()

            response = generate_npc_response(
                npc_id,
                utterance,
                case_world,
                provider_client=provider_client,
                system_prompt=system_prompt,
                response_schema=response_schema,
            )
            print("NPC Response Preview:")
            print(json.dumps(response, ensure_ascii=False, indent=2))
            failures = evaluate_expected_behavior(case_id, response)
            if failures:
                print("Expected behavior: FAIL - " + "; ".join(failures))
                print("Result: FAIL")
            else:
                print("Schema and Context grounding: PASS")
                print("Expected behavior: PASS")
                print("Result: PASS")
                passed += 1
    except (NpcResponseError, LLMProviderError, AssertionError) as exc:
        print(f"NPC Response Evaluation failed: {exc}")
    finally:
        state_unchanged = all(file_hash(path) == digest for path, digest in hashes_before.items())
        print(f"\nRead-only state check: {'PASS' if state_unchanged else 'FAIL'}")
        if not state_unchanged:
            return 1

    print(f"Summary: {passed}/{len(cases)} cases passed.")
    return 0 if passed == len(cases) else 1


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate a single-turn, read-only Grounded NPC Response."
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--test",
        action="store_true",
        help="run all eight NPC Response Evaluation cases",
    )
    mode.add_argument(
        "--test-case",
        type=int,
        choices=range(1, 9),
        metavar="NUMBER",
        help="run one NPC Response Evaluation case (1-8)",
    )
    parser.add_argument(
        "npc_id",
        nargs="?",
        help="Anchor NPC Entity ID, such as npc_astrid",
    )
    return parser.parse_args()


def main() -> int:
    configure_console_encoding()
    args = parse_args()
    load_dotenv(PROJECT_ROOT / ".env")
    try:
        world_state = load_world_state()
        if args.test or args.test_case is not None:
            return run_test_mode(world_state, args.test_case)
        if not args.npc_id:
            raise NpcResponseError("npc_id is required outside Evaluation mode.")

        context = build_npc_context(args.npc_id, world_state)
        print(f"Talking to {context['npc']['name']}")
        print("NPC Response Preview / Read-only")
        utterance = read_player_utterance()
        response = generate_npc_response(args.npc_id, utterance, world_state)
        print("\nNPC Response Preview:")
        print(json.dumps(response, ensure_ascii=False, indent=2))
        print("\nNo Persistent State was modified.")
        return 0
    except (NpcResponseError, LLMProviderError) as exc:
        print(f"NPC Response could not be generated: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
