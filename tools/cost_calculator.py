"""
AI模型成本计算模块（已迁移至 tools.cost_calculator）
提供基于token数量和模型价格的成本估算功能
"""


class CostCalculator:
    """AI模型成本计算器"""

    # 汇率常量
    USD_TO_CNY_RATE = 7.3

    # Gemini模型价格配置（每百万tokens的美元价格）
    GEMINI_PRICING = {
        '2.5-Flash': {
            'input_price': 0.3,
            'output_price': 2.5
        },
        '2.5-Pro': {
            'input_price': 1.25,
            'output_price': 10.0
        },
        '2.5-Flash-Lite': {
            'input_price': 0.1,
            'output_price': 0.4
        }
    }

    # Gemini缓存价格配置（每百万tokens的美元价格）
    GEMINI_CACHE_PRICING = {
        '2.5-Flash': {
            'cache_token_price': 0.075,
            'storage_price_per_hour': 1.00
        },
        '2.5-Pro': {
            'cache_token_price_small': 0.31,   # <= 20万tokens
            'cache_token_price_large': 0.625,  # > 20万tokens
            'storage_price_per_hour': 4.50
        },
        '2.5-Flash-Lite': {
            'cache_token_price': 0.025,
            'storage_price_per_hour': 1.00
        }
    }

    @classmethod
    def extract_model_name(cls, model_string):
        """从模型字符串提取标准模型名称"""
        if not model_string:
            return '2.5-Flash'  # 默认模型

        model_lower = model_string.lower()
        if 'pro' in model_lower:
            return '2.5-Pro'
        elif 'lite' in model_lower:
            return '2.5-Flash-Lite'
        else:
            return '2.5-Flash'

    @classmethod
    def calculate_cost(cls, model_name, total_input_tokens, output_tokens, cached_tokens=0):
        """
        计算API调用成本，正确处理缓存计费逻辑

        Args:
            model_name: 模型名称
            total_input_tokens: 总输入token数量（包括缓存的tokens）
            output_tokens: 输出token数量
            cached_tokens: 缓存的token数量（已包含在total_input_tokens中）

        Returns:
            dict: 包含各项成本信息的字典
        """
        try:
            # 标准化模型名称
            standard_model = cls.extract_model_name(model_name)

            # 获取价格配置
            if standard_model not in cls.GEMINI_PRICING:
                standard_model = '2.5-Flash'  # 默认使用Flash模型

            pricing = cls.GEMINI_PRICING[standard_model]

            # 计算新输入tokens（总输入 - 缓存）
            new_input_tokens = max(0, (total_input_tokens or 0) - (cached_tokens or 0))

            # 计算各项成本（价格是每百万tokens）
            # 1. 缓存tokens成本（使用模型特定的缓存价格）
            cache_cost_usd = 0
            if (cached_tokens or 0) > 0:
                cache_pricing = cls.GEMINI_CACHE_PRICING.get(standard_model, cls.GEMINI_CACHE_PRICING['2.5-Flash'])

                if standard_model == '2.5-Pro':
                    # Pro模型根据token数量使用不同价格
                    if cached_tokens <= 200_000:
                        cache_price = cache_pricing['cache_token_price_small']
                    else:
                        cache_price = cache_pricing['cache_token_price_large']
                else:
                    cache_price = cache_pricing['cache_token_price']

                cache_cost_usd = (cached_tokens / 1_000_000) * cache_price

            # 2. 新输入tokens成本（正常价格）
            new_input_cost_usd = (new_input_tokens / 1_000_000) * pricing['input_price']

            # 3. 输出tokens成本（正常价格）
            output_cost_usd = (output_tokens / 1_000_000) * pricing['output_price']

            # 总成本
            total_cost_usd = cache_cost_usd + new_input_cost_usd + output_cost_usd
            total_cost_cny = total_cost_usd * cls.USD_TO_CNY_RATE

            return {
                'model_name': standard_model,
                'total_input_tokens': total_input_tokens or 0,
                'new_input_tokens': new_input_tokens,
                'output_tokens': output_tokens or 0,
                'cached_tokens': cached_tokens or 0,
                'total_tokens': (total_input_tokens or 0) + (output_tokens or 0),
                'input_cost_usd': f"{cache_cost_usd + new_input_cost_usd:.6f}",
                'cache_cost_usd': f"{cache_cost_usd:.6f}",
                'output_cost_usd': f"{output_cost_usd:.6f}",
                'total_cost_usd': f"{total_cost_usd:.6f}",
                'total_cost_cny': f"{total_cost_cny:.4f}",
                'used_cache': (cached_tokens or 0) > 0
            }
        except Exception as e:
            # 出错时返回默认值
            return {
                'model_name': model_name or '2.5-Flash',
                'total_input_tokens': total_input_tokens or 0,
                'new_input_tokens': 0,
                'output_tokens': output_tokens or 0,
                'cached_tokens': cached_tokens or 0,
                'total_tokens': (total_input_tokens or 0) + (output_tokens or 0),
                'input_cost_usd': "0.000000",
                'cache_cost_usd': "0.000000",
                'output_cost_usd': "0.000000",
                'total_cost_usd': "0.000000",
                'total_cost_cny': "0.0000",
                'used_cache': cached_tokens > 0
            }

    @classmethod
    def parse_gemini_response_for_tokens(cls, response_data):
        """
        从Gemini API响应中解析token使用情况

        Args:
            response_data: Gemini API响应的JSON数据

        Returns:
            dict: token使用情况 {'input_tokens': int, 'output_tokens': int}
        """
        try:
            if isinstance(response_data, str):
                import json
                response_data = json.loads(response_data)

            # 查找usageMetadata
            usage_metadata = response_data.get('usageMetadata', {})

            input_tokens = usage_metadata.get('promptTokenCount', 0)
            output_tokens = usage_metadata.get('candidatesTokenCount', 0)

            return {
                'input_tokens': input_tokens,
                'output_tokens': output_tokens
            }

        except Exception as e:
            print(f"解析token使用情况失败: {e}")
            return {
                'input_tokens': 0,
                'output_tokens': 0
            }

    @classmethod
    def estimate_tokens_for_text(cls, text):
        """
        估算文本的token数量（简单估算，实际应使用tokenizer）

        Args:
            text: 文本内容

        Returns:
            int: 估算的token数量
        """
        if not text:
            return 0

        # 简单估算：英文约4个字符=1token，中文约1.5个字符=1token
        char_count = len(text)

        # 计算中英文字符比例进行估算
        chinese_chars = len([c for c in text if '\u4e00' <= c <= '\u9fff'])
        english_chars = char_count - chinese_chars

        estimated_tokens = int(english_chars / 4 + chinese_chars / 1.5)
        return max(estimated_tokens, 1)

    @classmethod
    def calculate_cache_cost(cls, tokens, ttl_hours, model_name='2.5-Flash'):
        """
        计算缓存成本

        Args:
            tokens: 缓存的token数量
            ttl_hours: 缓存生存时间（小时）
            model_name: 模型名称，用于确定缓存价格

        Returns:
            dict: 包含缓存成本信息的字典
        """
        try:
            # 标准化模型名称
            standard_model = cls.extract_model_name(model_name)

            # 获取模型的缓存价格配置
            cache_pricing = cls.GEMINI_CACHE_PRICING.get(standard_model, cls.GEMINI_CACHE_PRICING['2.5-Flash'])

            # 计算创建成本
            if standard_model == '2.5-Pro':
                # Pro模型根据token数量使用不同价格
                if tokens <= 200_000:
                    cache_price = cache_pricing['cache_token_price_small']
                else:
                    cache_price = cache_pricing['cache_token_price_large']
            else:
                cache_price = cache_pricing['cache_token_price']

            creation_cost = tokens * cache_price / 1_000_000
            storage_cost = tokens * ttl_hours * cache_pricing['storage_price_per_hour'] / 1_000_000
            total_cost = creation_cost + storage_cost

            return {
                'model_name': standard_model,
                'tokens': tokens,
                'ttl_hours': ttl_hours,
                'cache_price_per_million': cache_price,
                'creation_cost_usd': f"{creation_cost:.6f}",
                'storage_cost_usd': f"{storage_cost:.6f}",
                'total_cost_usd': f"{total_cost:.6f}",
                'total_cost_cny': f"{total_cost * cls.USD_TO_CNY_RATE:.4f}"
            }
        except Exception as e:
            return {
                'model_name': model_name or '2.5-Flash',
                'tokens': tokens or 0,
                'ttl_hours': ttl_hours or 0,
                'cache_price_per_million': 0.075,
                'creation_cost_usd': "0.000000",
                'storage_cost_usd': "0.000000",
                'total_cost_usd': "0.000000",
                'total_cost_cny': "0.0000",
                'error': str(e)
            }
