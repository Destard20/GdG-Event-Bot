import os
import requests
import base64
import logging
from core import config
from core.config import WP_URL, WP_USERNAME, WP_APP_PASSWORD, WP_POST_CATEGORY

logger = logging.getLogger(__name__)

def resolve_category_slug_or_name(category_str):
    """
    Attempts to resolve a category slug or name to its numeric WordPress ID via the REST API.
    Returns the integer ID if found, or None.
    """
    wp_url = getattr(config, "WP_URL", WP_URL)
    wp_username = getattr(config, "WP_USERNAME", WP_USERNAME)
    wp_password = getattr(config, "WP_APP_PASSWORD", WP_APP_PASSWORD)

    if not wp_url or not wp_username or not wp_password:
        logger.warning(f"WordPress credentials not configured to resolve category: {category_str}")
        return None

    url = f"{wp_url.rstrip('/')}/wp-json/wp/v2/categories"
    credentials = f"{wp_username}:{wp_password}"
    token = base64.b64encode(credentials.encode())
    headers = {
        'Authorization': f'Basic {token.decode("utf-8")}',
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36'
    }

    try:
        # Try finding by slug first
        resp = requests.get(url, headers=headers, params={'slug': category_str}, timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            if isinstance(data, list) and len(data) > 0:
                return data[0].get('id')

        # Try searching by name
        resp = requests.get(url, headers=headers, params={'search': category_str}, timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            if isinstance(data, list):
                for cat in data:
                    if (cat.get('name', '').strip().lower() == category_str.strip().lower() or
                        cat.get('slug', '').strip().lower() == category_str.strip().lower()):
                        return cat.get('id')

        logger.warning(f"Could not resolve WordPress category: {category_str}")
        return None
    except Exception as e:
        logger.error(f"Error resolving WordPress category '{category_str}': {e}")
        return None

def get_category_ids(category_input=None):
    """
    Resolves category_input (or the WP_POST_CATEGORY env variable) to a list of integer IDs.
    Returns None if missing, empty, or unresolvable.
    Supports integer IDs, comma-separated IDs, or category slug/name resolution.
    """
    if category_input is not None:
        target = category_input
    elif getattr(config, "WP_POST_CATEGORY", None) is not None:
        target = config.WP_POST_CATEGORY
    else:
        target = WP_POST_CATEGORY

    if target is None:
        return None

    if isinstance(target, int):
        return [target] if target > 0 else None

    if isinstance(target, (list, tuple)):
        result = []
        for item in target:
            if isinstance(item, int) and item > 0:
                result.append(item)
            elif isinstance(item, str) and item.strip().isdigit() and int(item.strip()) > 0:
                result.append(int(item.strip()))
        return result if result else None

    target_str = str(target).strip()
    if not target_str:
        return None

    parts = [p.strip() for p in target_str.split(',') if p.strip()]
    if not parts:
        return None

    if all(p.isdigit() for p in parts):
        ids = [int(p) for p in parts if int(p) > 0]
        return ids if ids else None

    resolved_ids = []
    for part in parts:
        if part.isdigit() and int(part) > 0:
            resolved_ids.append(int(part))
        else:
            cat_id = resolve_category_slug_or_name(part)
            if cat_id:
                resolved_ids.append(cat_id)

    return resolved_ids if resolved_ids else None

def upload_media(filepath):
    wp_url = getattr(config, "WP_URL", WP_URL)
    wp_username = getattr(config, "WP_USERNAME", WP_USERNAME)
    wp_password = getattr(config, "WP_APP_PASSWORD", WP_APP_PASSWORD)

    if not wp_url or not wp_username or not wp_password:
        logger.warning("WordPress credentials not fully configured for media upload.")
        return None
        
    url = f"{wp_url.rstrip('/')}/wp-json/wp/v2/media"
    credentials = f"{wp_username}:{wp_password}"
    token = base64.b64encode(credentials.encode())
    
    filename = os.path.basename(filepath)
    headers = {
        'Authorization': f'Basic {token.decode("utf-8")}',
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36',
        'Content-Disposition': f'attachment; filename="{filename}"'
    }
    
    try:
        with open(filepath, 'rb') as f:
            media_data = f.read()
            
        import mimetypes
        content_type, _ = mimetypes.guess_type(filepath)
        if content_type:
            headers['Content-Type'] = content_type
            
        response = requests.post(url, headers=headers, data=media_data)
        if response.status_code in [200, 201]:
            logger.info("Image uploaded to WordPress successfully.")
            resp_json = response.json()
            return {'id': resp_json.get('id'), 'source_url': resp_json.get('source_url')}
        else:
            logger.error(f"Failed to upload media to WP: {response.status_code} - {response.text}")
            return None
    except Exception as e:
        logger.error(f"Error uploading media to WP: {e}")
        return None

def publish_article(title, content, media_id=None, category=None):
    wp_url = getattr(config, "WP_URL", WP_URL)
    wp_username = getattr(config, "WP_USERNAME", WP_USERNAME)
    wp_password = getattr(config, "WP_APP_PASSWORD", WP_APP_PASSWORD)

    if not wp_url or not wp_username or not wp_password:
        logger.warning("WordPress credentials not fully configured.")
        return False, None
        
    url = f"{wp_url.rstrip('/')}/wp-json/wp/v2/posts"
    credentials = f"{wp_username}:{wp_password}"
    token = base64.b64encode(credentials.encode())
    
    headers = {
        'Authorization': f'Basic {token.decode("utf-8")}',
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36'
    }
    
    data = {
        'title': title,
        'content': content,
        'status': 'draft' # Or 'publish'
    }
    
    if media_id:
        data['featured_media'] = media_id

    category_ids = get_category_ids(category)
    if category_ids:
        data['categories'] = category_ids
        
    try:
        response = requests.post(url, headers=headers, json=data)
        if response.status_code in [200, 201]:
            logger.info("Article published to WordPress successfully.")
            resp_json = response.json()
            post_id = resp_json.get('id')
            edit_link = f"{wp_url.rstrip('/')}/wp-admin/post.php?post={post_id}&action=edit"
            return edit_link, post_id
        else:
            logger.error(f"Failed to publish to WP: {response.status_code} - {response.text}")
            return False, None
    except Exception as e:
        logger.error(f"Error publishing to WP: {e}")
        return False, None

def update_article_status(post_id, status='publish'):
    wp_url = getattr(config, "WP_URL", WP_URL)
    wp_username = getattr(config, "WP_USERNAME", WP_USERNAME)
    wp_password = getattr(config, "WP_APP_PASSWORD", WP_APP_PASSWORD)

    if not wp_url or not wp_username or not wp_password:
        logger.warning("WordPress credentials not fully configured.")
        return False
        
    url = f"{wp_url.rstrip('/')}/wp-json/wp/v2/posts/{post_id}"
    credentials = f"{wp_username}:{wp_password}"
    token = base64.b64encode(credentials.encode())
    
    headers = {
        'Authorization': f'Basic {token.decode("utf-8")}',
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36'
    }
    
    data = {
        'status': status
    }
    
    try:
        response = requests.post(url, headers=headers, json=data)
        if response.status_code in [200, 201]:
            logger.info(f"Article {post_id} status updated to {status}.")
            return True
        else:
            logger.error(f"Failed to update article status on WP: {response.status_code} - {response.text}")
            return False
    except Exception as e:
        logger.error(f"Error updating article status on WP: {e}")
        return False

