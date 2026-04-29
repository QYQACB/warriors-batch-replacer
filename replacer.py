#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import requests
import time
import sys
import os
import getpass
import json

# ============== 配置 ==============
API_URL = "https://warriors.huijiwiki.com/api.php"
# 建议优先使用环境变量，避免命令行泄露密码
USERNAME = os.environ.get("WIKI_USERNAME")
PASSWORD = os.environ.get("WIKI_PASSWORD")

# 如果环境变量未设置，提示用户输入（更安全）
if not USERNAME or not PASSWORD:
    if not USERNAME:
        USERNAME = input("请输入用户名: ")
    if not PASSWORD:
        PASSWORD = getpass.getpass("请输入密码 (输入时不可见): ")

# ============== 替换规则 ==============
REPLACE_RULES = [
    ('花蜜鸣', '花蜜歌'),
    # ('原词', '新词'),
]

# ============== 会话管理 ==============
session = requests.Session()
session.headers.update({
    'User-Agent': 'WarriorsBot/1.0 (YourContactInfo@example.com)'
})

def login():
    """登录维基 (尝试使用 clientlogin，如果失败则回退或报错)"""
    print("正在登录...")
    
    # 1. 获取登录 token
    try:
        r = session.get(API_URL, params={
            'action': 'query',
            'meta': 'tokens',
            'type': 'login',
            'format': 'json'
        })
        r.raise_for_status()
        data = r.json()
        login_token = data['query']['tokens']['logintoken']
    except Exception as e:
        print(f"❌ 获取登录 Token 失败: {e}")
        return False

    # 2. 执行登录 (注意：HuijiWiki 可能要求使用 clientlogin，此处保留旧版作为示例，
    #    如果失败，请查阅 HuijiWiki 文档改用 action=clientlogin)
    try:
        r = session.post(API_URL, data={
            'action': 'login',
            'lgname': USERNAME,
            'lgpassword': PASSWORD,
            'lgtoken': login_token,
            'format': 'json'
        })
        r.raise_for_status()
        result = r.json()
        
        # 检查登录结果
        login_result = result.get('login', {})
        status = login_result.get('result')
        
        if status == 'Success':
            print(f'✅ 登录成功: {USERNAME}')
            return True
        elif status == 'NeedToken':
            # 某些情况下需要第二次请求携带 cookie，但现代 requests session 通常自动处理
            print("⚠️ 需要二次 Token 验证，尝试重试...")
            # 这里可以添加重试逻辑，但通常 lgtoken 已足够
            return False
        else:
            print(f'❌ 登录失败: {status} - {login_result.get("reason", "未知原因")}')
            return False
            
    except Exception as e:
        print(f"❌ 登录请求异常: {e}")
        return False

def get_csrf_token():
    """获取编辑 token"""
    try:
        r = session.get(API_URL, params={
            'action': 'query',
            'meta': 'tokens',
            'format': 'json'
        })
        r.raise_for_status()
        return r.json()['query']['tokens']['csrftoken']
    except Exception as e:
        print(f"❌ 获取 CSRF Token 失败: {e}")
        sys.exit(1)

def get_page_info(title):
    """获取页面原始内容和 revid"""
    try:
        r = session.get(API_URL, params={
            'action': 'query',
            'titles': title,
            'prop': 'revisions',
            'rvprop': 'content|ids',
            'format': 'json'
        })
        r.raise_for_status()
        data = r.json()
        pages = data['query']['pages']
        page_id = next(iter(pages))
        
        if page_id == '-1':
            return None, None, None # 页面不存在
            
        page_data = pages[page_id]
        if 'revisions' not in page_data:
            return None, None, None
            
        rev = page_data['revisions']
        return rev['*'], rev['revid'], page_data.get('missing', False)
        
    except Exception as e:
        raise Exception(f"获取页面 {title} 失败: {e}")

def apply_replacements(text):
    """对文本应用所有替换规则"""
    for old, new in REPLACE_RULES:
        text = text.replace(old, new)
    return text

def save_page(title, text, summary, token, baserevid):
    """保存页面"""
    try:
        r = session.post(API_URL, data={
            'action': 'edit',
            'title': title,
            'text': text,
            'summary': summary,
            'token': token,
            'bot': 'true',
            'baserevid': baserevid,  # 防止编辑冲突
            'format': 'json'
        })
        r.raise_for_status()
        return r.json()
    except Exception as e:
        raise Exception(f"保存页面 {title} 失败: {e}")

def main():
    print('=' * 50)
    print('猫武士维基批量替换机器人')
    print(f'替换规则: {len(REPLACE_RULES)} 条')
    for a, b in REPLACE_RULES:
        print(f'  "{a}" → "{b}"')
    print('=' * 50)
    
    # 登录
    if not login():
        return
    
    # 获取CSRF token
    csrf_token = get_csrf_token()
    print('已获取编辑 token')
    
    # 获取页面列表 (简化版：仅获取前100页用于测试，生产环境请移除 aplimit 或使用生成器)
    print('正在获取页面列表...')
    pages = []
    apcontinue = None
    while True:
        params = {
            'action': 'query',
            'list': 'allpages',
            'aplimit': 500,
            'format': 'json'
        }
        if apcontinue:
            params['apcontinue'] = apcontinue
            
        try:
            r = session.get(API_URL, params=params)
            r.raise_for_status()
            data = r.json()
        except Exception as e:
            print(f"❌ 获取页面列表失败: {e}")
            return

        for page in data['query']['allpages']:
            pages.append(page['title'])
        
        if 'continue' in data and 'apcontinue' in data['continue']:
            apcontinue = data['continue']['apcontinue']
        else:
            break
    
    print(f'共有 {len(pages)} 个页面需扫描')
    print()
    
    # 统计
    replaced = 0
    skipped = 0
    failed = 0
    
    for i, title in enumerate(pages, 1):
        progress = f'[{i}/{len(pages)}]'
        print(f'{progress} {title[:40]:<40}', end='', flush=True)
        
        try:
            # 获取原始内容和 revid
            raw, revid, is_missing = get_page_info(title)
            
            if is_missing or raw is None:
                print('  ➡️ 跳过(无效页面)')
                skipped += 1
                continue
            
            # 检查是否需要替换
            need_replace = any(old in raw for old, _ in REPLACE_RULES)
            if not need_replace:
                print('  ➡️ 跳过(无匹配)')
                skipped += 1
                continue
            
            # 执行替换
            new_text = apply_replacements(raw)
            
            if new_text == raw:
                print('  ➡️ 跳过(无需修改)')
                skipped += 1
                continue
            
            # 保存页面
            result = save_page(title, new_text, '机器人：批量替换文本', csrf_token, revid)
            
            edit_result = result.get('edit', {})
            if edit_result.get('result') == 'Success':
                print('  ✅ 已修改')
                replaced += 1
            elif edit_result.get('result') == 'Failure':
                 # 处理编辑冲突或其他错误
                 err_code = edit_result.get('code', 'Unknown')
                 if err_code == 'editconflict':
                     print('  ⚠️ 编辑冲突，跳过')
                     skipped += 1
                 else:
                     print(f'  ❌ 保存失败: {edit_result.get("info", "未知错误")}')
                     failed += 1
            else:
                print(f'  ❌ 未知响应: {result}')
                failed += 1
            
            # 限速
            time.sleep(0.5)
            
        except Exception as e:
            print(f'  ❌ 错误: {str(e)}')
            failed += 1
            time.sleep(2)
        
        # 每50个页面刷新一次token
        if i % 50 == 0:
            print(f'\n--- 刷新 token ---')
            csrf_token = get_csrf_token()
            print(f'--- 继续处理 ---\n')
    
    # 结果汇总
    print()
    print('=' * 50)
    print('运行完成！')
    print(f'✅ 已替换: {replaced}')
    print(f'➡️ 已跳过: {skipped}')
    print(f'❌ 已失败: {failed}')
    print('=' * 50)

if __name__ == '__main__':
    main()
