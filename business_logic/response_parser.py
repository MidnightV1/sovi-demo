from __future__ import annotations
from typing import Any, Dict, Optional
import xml.etree.ElementTree as ET
from api_clients.response_types import ParsedXmlData
from business_logic.exceptions import XmlParseError


class ResponseParser:
    """响应解析器 - 迁移自 gemini_client.parse_xml_response（保持行为一致）。"""

    def parse_xml_response(self, response_text: str) -> ParsedXmlData:
        try:
            start_tag = "<Sovi_Response>"
            end_tag = "</Sovi_Response>"

            start_idx = response_text.find(start_tag)
            end_idx = response_text.find(end_tag)

            # 若不包含 Sovi 标签：
            # - 文本看起来像 XML（包含尖括号），按照兼容策略直接透传为显示内容；
            # - 否则认为结构不完整，抛出解析异常。
            if start_idx == -1 or end_idx == -1:
                if ('<' in response_text) and ('>' in response_text):
                    return ParsedXmlData(raw_response=response_text, display_content=response_text)
                raise XmlParseError(response_text, 'XML结构不完整')

            xml_content = response_text[start_idx:end_idx + len(end_tag)]

            root = ET.fromstring(xml_content)

            result: Dict[str, Any] = {
                'raw_response': response_text,
                'display_content': '',
            }

            for child in root:
                if child.tag == 'Action_Mode':
                    result['action_mode'] = child.text.strip() if child.text else ''
                elif child.tag == 'Is_Valid_Question':
                    result['is_valid_question'] = child.text.strip().lower() == 'true' if child.text else False
                elif child.tag == 'Sovi_Explanation':
                    result['explanation'] = child.text.strip() if child.text else ''
                elif child.tag == 'Sovi_Response_Msg':
                    result['response_msg'] = child.text.strip() if child.text else ''
                    result['display_content'] = child.text.strip() if child.text else ''
                elif child.tag == 'Session_Meta':
                    session_meta: Dict[str, Any] = {}
                    for sub_child in child:
                        if sub_child.tag == 'Title':
                            session_meta['title'] = sub_child.text.strip() if sub_child.text else ''
                        elif sub_child.tag == 'Summary':
                            session_meta['summary'] = sub_child.text.strip() if sub_child.text else ''
                    result['session_meta'] = session_meta
                elif child.tag == 'Question_Meta':
                    question_meta: Dict[str, Any] = {}
                    for sub_child in child:
                        if sub_child.tag == 'Subject':
                            question_meta['subject'] = sub_child.text.strip() if sub_child.text else ''
                        elif sub_child.tag == 'Complexity':
                            question_meta['complexity'] = sub_child.text.strip() if sub_child.text else ''
                        elif sub_child.tag == 'Concepts':
                            question_meta['concepts'] = sub_child.text.strip() if sub_child.text else ''
                    result['question_meta'] = question_meta
                    try:
                        # 保留原始 Question_Meta XML，用于DB层持久化 full_xml_content
                        result['question_meta_xml'] = ET.tostring(child, encoding='unicode')
                    except Exception:
                        pass

            # working_content
            working_content = result.get('display_content', '')
            if (result.get('action_mode', '').strip() == 'Mode1' and result.get('explanation')):
                working_content = f"### Sovi_Explanation\n{result['explanation']}\n### Sovi_Response_Msg\n{result['display_content']}"
            result['working_content'] = working_content

            # profile update
            profile_update_data = self.extract_user_profile(response_text)
            if profile_update_data:
                result['profile_update'] = {
                    'profile_update_required': True,
                    'updated_user_profile': profile_update_data
                }

            if not result.get('display_content'):
                result['display_content'] = response_text

            # 将受支持字段构造成 ParsedXmlData，其它扩展字段如 question_meta_xml 以属性形式附加
            supported_keys = {k: result.get(k) for k in (
                'raw_response','display_content','working_content','error','raw_text',
                'action_mode','is_valid_question','explanation','response_msg',
                'session_meta','question_meta','profile_update'
            )}
            parsed = ParsedXmlData(**supported_keys)
            # 附加扩展字段
            if 'question_meta_xml' in result:
                setattr(parsed, 'question_meta_xml', result['question_meta_xml'])
            return parsed

        except XmlParseError as e:
            # 保持原始 XmlParseError，不做二次包装
            raise e
        except ET.ParseError as e:
            raise XmlParseError(response_text, f'XML解析错误: {str(e)}')
        except Exception as e:
            raise XmlParseError(response_text, f'解析错误: {str(e)}')

    def extract_user_profile(self, response_text: str) -> Optional[str]:
        try:
            start_tag = "<User_Basic_Profile>"
            end_tag = "</User_Basic_Profile>"

            start_idx = response_text.find(start_tag)
            end_idx = response_text.find(end_tag)

            if start_idx == -1 or end_idx == -1:
                return None

            profile_content = response_text[start_idx:end_idx + len(end_tag)]
            root = ET.fromstring(profile_content)

            update_required = root.find('Profile_Update_Required')
            if update_required is None or (update_required.text or '').strip().lower() != 'true':
                return None

            updated_profile = root.find('Updated_User_Profile')
            if updated_profile is not None and updated_profile.text:
                return updated_profile.text.strip()

            return None
        except ET.ParseError:
            return None
        except Exception:
            return None
