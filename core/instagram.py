import requests
import logging
import asyncio
from core.config import IG_ACCESS_TOKEN, IG_ACCOUNT_ID

logger = logging.getLogger(__name__)

async def publish_instagram_story(image_url):
    if not IG_ACCESS_TOKEN or not IG_ACCOUNT_ID:
        logger.warning("Instagram credentials not fully configured.")
        return False, "Credenziali Instagram non configurate."

    # 1. Create Media Container
    container_url = f"https://graph.facebook.com/v20.0/{IG_ACCOUNT_ID}/media"
    container_payload = {
        'image_url': image_url,
        'media_type': 'STORIES',
        'access_token': IG_ACCESS_TOKEN
    }
    
    try:
        response = requests.post(container_url, data=container_payload)
        resp_json = response.json()
        
        if 'id' not in resp_json:
            logger.error(f"IG Create Container Failed: {resp_json}")
            return False, f"Errore creazione container IG: {resp_json.get('error', {}).get('message', 'Sconosciuto')}"
            
        creation_id = resp_json['id']
        logger.info(f"IG Container created with ID: {creation_id}")
        
        # 2. Wait a moment for Meta to process the image container before publishing
        await asyncio.sleep(5)
        
        # 3. Publish the Media Container
        publish_url = f"https://graph.facebook.com/v20.0/{IG_ACCOUNT_ID}/media_publish"
        publish_payload = {
            'creation_id': creation_id,
            'access_token': IG_ACCESS_TOKEN
        }
        
        pub_response = requests.post(publish_url, data=publish_payload)
        pub_json = pub_response.json()
        
        if 'id' not in pub_json:
            logger.error(f"IG Publish Media Failed: {pub_json}")
            return False, f"Errore pubblicazione IG: {pub_json.get('error', {}).get('message', 'Sconosciuto')}"
            
        logger.info(f"IG Story published successfully with ID: {pub_json['id']}")
        return True, "Storia pubblicata con successo!"
        
    except Exception as e:
        logger.error(f"Exception during IG Publish: {e}")
        return False, f"Eccezione durante la pubblicazione: {e}"