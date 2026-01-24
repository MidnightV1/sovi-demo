from core.service_container import ServiceContainer
from business_logic.response_parser import ResponseParser
from prompts.system_prompts import SystemPrompts
from api_clients.response_types import ParsedXmlData
from business_logic.exceptions import XmlParseError


def test_service_container_singleton_and_factory():
    c = ServiceContainer()
    c.register_singleton('parser', ResponseParser())
    c.register_factory('prompt', lambda: SystemPrompts())

    p1 = c.get('parser')
    p2 = c.get('parser')
    assert p1 is p2

    s1 = c.get('prompt')
    s2 = c.get('prompt')
    assert s1 is s2  # factories are cached after first creation


def test_response_parser_min_impl():
    parser = ResponseParser()
    raw = "<response><content>hello</content></response>"
    parsed = parser.parse_xml_response(raw)
    assert isinstance(parsed, ParsedXmlData)
    assert parsed.display_content == raw
    assert parsed.raw_response == raw


def test_system_prompts_min_impl():
    base = SystemPrompts.get_main_prompt()
    assert isinstance(base, str) and len(base) > 0

    with_profile = SystemPrompts.get_welcome_prompt("CS freshman")
    assert "CS freshman" in with_profile


def test_response_parser_full_logic_happy_path():
    parser = ResponseParser()
    xml = (
        "<Sovi_Response>"
        "<Action_Mode>Mode1</Action_Mode>"
        "<Is_Valid_Question>True</Is_Valid_Question>"
        "<Sovi_Explanation>explain</Sovi_Explanation>"
        "<Sovi_Response_Msg>final</Sovi_Response_Msg>"
        "<Session_Meta><Title>T</Title><Summary>S</Summary></Session_Meta>"
        "<Question_Meta><Subject>math</Subject><Complexity>basic</Complexity><Concepts>a,b</Concepts></Question_Meta>"
        "</Sovi_Response>"
    )
    parsed = parser.parse_xml_response(xml)
    assert parsed.action_mode == 'Mode1'
    assert parsed.is_valid_question is True
    assert parsed.explanation == 'explain'
    assert parsed.response_msg == 'final'
    assert parsed.display_content == 'final'
    assert parsed.session_meta == {'title': 'T', 'summary': 'S'}
    assert parsed.question_meta == {'subject': 'math', 'complexity': 'basic', 'concepts': 'a,b'}
    assert parsed.working_content.startswith('### Sovi_Explanation')


def test_response_parser_incomplete_xml():
    parser = ResponseParser()
    text = "no tags here"
    try:
        parser.parse_xml_response(text)
        assert False, "should raise XmlParseError"
    except XmlParseError as e:
        assert "XML" in str(e)
