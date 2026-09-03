import os
import requests
import base64
import logging
from core.config import WP_URL, WP_USERNAME, WP_APP_PASSWORD

logger = logging.getLogger(__name__)

def upload_media(filepath):
    if not WP_URL or not WP_USERNAME or not WP_APP_PASSWORD:
        logger.warning("WordPress credentials not fully configured for media upload.")
        return None
        
    url = f"{WP_URL.rstrip('/')}/wp-json/wp/v2/media"
    credentials = f"{WP_USERNAME}:{WP_APP_PASSWORD}"
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

def publish_article(title, content, media_id=None):
    if not WP_URL or not WP_USERNAME or not WP_APP_PASSWORD:
        logger.warning("WordPress credentials not fully configured.")
        return False
        
    url = f"{WP_URL.rstrip('/')}/wp-json/wp/v2/posts"
    credentials = f"{WP_USERNAME}:{WP_APP_PASSWORD}"
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
        
    try:
        response = requests.post(url, headers=headers, json=data)
        if response.status_code in [200, 201]:
            logger.info("Article published to WordPress successfully.")
            resp_json = response.json()
            post_id = resp_json.get('id')
            edit_link = f"{WP_URL.rstrip('/')}/wp-admin/post.php?post={post_id}&action=edit"
            return edit_link, post_id
        else:
            logger.error(f"Failed to publish to WP: {response.status_code} - {response.text}")
            return False, None
    except Exception as e:
        logger.error(f"Error publishing to WP: {e}")
        return False, None

def update_article_status(post_id, status='publish'):
    if not WP_URL or not WP_USERNAME or not WP_APP_PASSWORD:
        logger.warning("WordPress credentials not fully configured.")
        return False
        
    url = f"{WP_URL.rstrip('/')}/wp-json/wp/v2/posts/{post_id}"
    credentials = f"{WP_USERNAME}:{WP_APP_PASSWORD}"
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

