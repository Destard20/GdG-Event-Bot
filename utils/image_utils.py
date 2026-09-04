import os
import uuid
from PIL import Image, ImageOps, ImageDraw, ImageFont
from pilmoji import Pilmoji
import logging
import textwrap
from datetime import datetime
from core.config import FONTS_DIR

logger = logging.getLogger(__name__)

def get_daily_dir(base_dir, date_str=None):
    if date_str:
        try:
            # Expected format DD-MM-YYYY
            parts = date_str.split('-')
            if len(parts) == 3:
                d, m, y = parts
                target_date = datetime(int(y), int(m), int(d))
            else:
                target_date = datetime.now()
        except Exception:
            target_date = datetime.now()
    else:
        target_date = datetime.now()
        
    daily_dir = os.path.join(base_dir, target_date.strftime("%Y"), target_date.strftime("%m"), target_date.strftime("%d"))
    if not os.path.exists(daily_dir):
        os.makedirs(daily_dir)
    return daily_dir

def save_image_locally(image_bytes, data_dir, date_str=None):
    try:
        daily_dir = get_daily_dir(data_dir, date_str)
        filename = f"event_{uuid.uuid4()}.jpg"
        filepath = os.path.join(daily_dir, filename)
        with open(filepath, 'wb') as f:
            f.write(image_bytes)
        return filepath
    except Exception as e:
        logger.error(f"Error saving image: {e}")
        return None

def delete_local_image(filepath):
    try:
        if filepath and os.path.exists(filepath):
            os.remove(filepath)
    except Exception as e:
        logger.error(f"Error deleting image {filepath}: {e}")

def build_horizontal_collage(images):
    """
    Given a list of PIL Image objects, resizes them proportionally to their average height
    and stitches them horizontally side by side without stretching or cropping.
    """
    if not images:
        return None
    if len(images) == 1:
        im = images[0]
        if im.mode != 'RGB':
            im = im.convert('RGB')
        return im

    processed_images = []
    for im in images:
        try:
            im = ImageOps.exif_transpose(im)
        except Exception:
            pass
        if im.mode != 'RGB':
            im = im.convert('RGB')
        processed_images.append(im)

    widths, heights = zip(*(i.size for i in processed_images))
    avg_height = max(1, int(sum(heights) / len(processed_images)))

    # Resize images so they all have the exact same height (the average height),
    # allowing their widths to adjust naturally.
    resized_images = []
    for im in processed_images:
        new_width = max(1, int(im.width * (avg_height / im.height)))
        resized_images.append(im.resize((new_width, avg_height), Image.Resampling.LANCZOS))

    new_widths = [im.width for im in resized_images]
    total_width = sum(new_widths)
    max_height = avg_height

    collage = Image.new('RGB', (total_width, max_height))

    x_offset = 0
    for im in resized_images:
        collage.paste(im, (x_offset, 0))
        x_offset += im.width

    return collage

def create_collage(image_paths, output_dir, date_str=None):
    if not image_paths:
        return None
    
    try:
        images = []
        for p in image_paths:
            if p and os.path.exists(p):
                images.append(Image.open(p))
        if not images:
            return None
            
        collage = build_horizontal_collage(images)
        if not collage:
            return None
            
        daily_dir = get_daily_dir(output_dir, date_str)
        filename = f"collage_{uuid.uuid4()}.jpg"
        filepath = os.path.join(daily_dir, filename)
        collage.save(filepath)
        return filepath
    except Exception as e:
        logger.error(f"Error creating collage: {e}")
        return None

def create_collage_from_bytes(images_bytes_list):
    """
    Given a list of image byte arrays, creates a single horizontal collage
    and returns the resulting JPEG image as bytes.
    """
    if not images_bytes_list:
        return None
    if len(images_bytes_list) == 1:
        return images_bytes_list[0]

    try:
        import io
        images = []
        for b in images_bytes_list:
            if b:
                images.append(Image.open(io.BytesIO(b)))
        if not images:
            return None

        collage = build_horizontal_collage(images)
        if not collage:
            return None

        out_buf = io.BytesIO()
        collage.save(out_buf, format='JPEG', quality=95)
        return out_buf.getvalue()
    except Exception as e:
        logger.error(f"Error creating collage from bytes: {e}")
        return None

def create_story_image(event_data, original_image_path, output_dir):
    try:
        # Instagram Story dimensions
        STORY_WIDTH, STORY_HEIGHT = 1080, 1920
        story_img = Image.new('RGB', (STORY_WIDTH, STORY_HEIGHT), color=(20, 20, 20)) # Dark background
        
        # Process and paste the original image at the top
        if original_image_path and os.path.exists(original_image_path):
            with Image.open(original_image_path) as im:
                # Resize image to fit width, maintaining aspect ratio
                new_height = int(im.height * (STORY_WIDTH / im.width))
                im_resized = im.resize((STORY_WIDTH, new_height), Image.Resampling.LANCZOS)
                
                # If the image is insanely tall, crop it so it doesn't cover the whole screen
                max_img_height = int(STORY_HEIGHT * 0.55)
                if new_height > max_img_height:
                    im_resized = ImageOps.fit(im, (STORY_WIDTH, max_img_height), Image.Resampling.LANCZOS)
                    new_height = max_img_height
                    
                story_img.paste(im_resized, (0, 0))
                y_text_start = new_height + 50
        else:
            y_text_start = 100
            
        # Draw Text
        with Pilmoji(story_img) as pilmoji:
            try:
                # Try to load downloaded Roboto fonts, fallback to default if missing
                font_bold = ImageFont.truetype(os.path.join(FONTS_DIR, "Roboto-Bold.ttf"), 50)
                font_regular = ImageFont.truetype(os.path.join(FONTS_DIR, "Roboto-Regular.ttf"), 40)
                font_desc = ImageFont.truetype(os.path.join(FONTS_DIR, "Roboto-Regular.ttf"), 35)
            except Exception:
                logger.warning("Could not load custom fonts, using default.")
                font_bold = ImageFont.load_default()
                font_regular = ImageFont.load_default()
                font_desc = ImageFont.load_default()

            margin = 60
            y = y_text_start
            
            # Helper function to measure wrapped text height
            def measure_wrapped_text_height(text, font_size, max_width_chars):
                if not text: return 0
                raw_lines = text.split('\n')
                line_height = font_size + 10
                total_h = 0
                for r_line in raw_lines:
                    r_line = r_line.strip()
                    if not r_line:
                        total_h += int(font_size * 0.5)
                        continue
                    lines = textwrap.wrap(r_line, width=max_width_chars)
                    total_h += len(lines) * line_height
                return total_h

            # Helper function to draw wrapped text preserving explicit newlines
            def draw_wrapped_text(text, font, max_width_chars, y_pos, x_pos, color=(255, 255, 255), max_y=None):
                if not text: return y_pos
                raw_lines = text.split('\n')
                all_lines = []
                for r_line in raw_lines:
                    r_line = r_line.strip()
                    if not r_line:
                        all_lines.append(None)
                    else:
                        all_lines.extend(textwrap.wrap(r_line, width=max_width_chars))
                
                line_height = font.size + 10
                for idx, line in enumerate(all_lines):
                    if line is None:
                        y_pos += int(font.size * 0.5)
                        continue
                    if max_y and (y_pos + line_height > max_y):
                        break
                    is_last_fit = max_y and (y_pos + line_height * 2 > max_y)
                    has_more = (idx < len(all_lines) - 1)
                    if is_last_fit and has_more:
                        line_to_draw = line[:-3] + "..." if len(line) > 3 else line + "..."
                        pilmoji.text((x_pos, y_pos), line_to_draw, font=font, fill=color)
                        y_pos += line_height
                        break
                    else:
                        pilmoji.text((x_pos, y_pos), line, font=font, fill=color)
                        y_pos += line_height
                return y_pos

            # Draw Title
            title = event_data.get('title', 'Evento')
            title_text = f"📣 {title}"
            char_width_title = int((STORY_WIDTH - (margin * 2)) / (font_bold.size * 0.5))
            y = draw_wrapped_text(title_text, font_bold, char_width_title, y, margin, color=(255, 255, 255))
            y += 20
            
            # Draw Details
            max_s = event_data.get('max_seats')
            if max_s is None:
                seats_display = "Nessun limite"
            else:
                seats_display = str(max_s)
                
            details = [
                ("📅 Data:", event_data.get('date', 'N/A')),
                ("🎲 Sistema:", event_data.get('system', 'N/A')),
                ("🪑 Posti:", seats_display)
            ]
            
            for label, value in details:
                if value and value != 'N/A':
                    pilmoji.text((margin, y), label, font=font_bold, fill=(200, 200, 200))
                    char_width_val = int((STORY_WIDTH - margin - 260 - margin) / (font_regular.size * 0.5))
                    y = draw_wrapped_text(value, font_regular, char_width_val, y, margin + 260, color=(255, 255, 255))
                    y += 10
                    
            y += 10
            
            # Draw Extra Info (Dettagli)
            extra = (event_data.get('extra_info') or '').strip()
            if extra:
                pilmoji.text((margin, y), "🏷️ Dettagli:", font=font_bold, fill=(200, 200, 200))
                y += font_bold.size + 10
                char_width_extra = int((STORY_WIDTH - (margin * 2)) / (font_regular.size * 0.5))
                y = draw_wrapped_text(extra, font_regular, char_width_extra, y, margin, color=(240, 240, 240))
                y += 20
                
            # Draw Description
            desc = (event_data.get('description') or '').strip()
            if desc:
                desc_text = f"📝 {desc}"
                max_y = STORY_HEIGHT - margin
                available_height = max(80, max_y - y)
                
                # Dynamically choose font size from 35 down to 20 to fit available height
                chosen_size = 35
                for sz in range(35, 19, -2):
                    c_w = int((STORY_WIDTH - (margin * 2)) / (sz * 0.5))
                    h = measure_wrapped_text_height(desc_text, sz, c_w)
                    chosen_size = sz
                    if h <= available_height:
                        break
                
                try:
                    font_desc_dynamic = ImageFont.truetype(os.path.join(FONTS_DIR, "Roboto-Regular.ttf"), chosen_size)
                except Exception:
                    font_desc_dynamic = ImageFont.load_default()
                    
                char_width_wrap = int((STORY_WIDTH - (margin * 2)) / (font_desc_dynamic.size * 0.5))
                y = draw_wrapped_text(desc_text, font_desc_dynamic, char_width_wrap, y, margin, color=(220, 220, 220), max_y=max_y)

        # Save
        daily_dir = get_daily_dir(output_dir, event_data.get('normalized_date'))
        filename = f"story_{uuid.uuid4()}.jpg"
        filepath = os.path.join(daily_dir, filename)
        story_img.save(filepath, quality=90)
        return filepath
        
    except Exception as e:
        logger.error(f"Error creating story image: {e}")
        return None

def create_recap_story_image(events, collage_path, date_str, output_dir):
    try:
        # Instagram Story dimensions
        STORY_WIDTH, STORY_HEIGHT = 1080, 1920
        story_img = Image.new('RGB', (STORY_WIDTH, STORY_HEIGHT), color=(20, 20, 20)) # Dark background
        
        # Process and paste the collage at the top
        if collage_path and os.path.exists(collage_path):
            with Image.open(collage_path) as im:
                # Resize image to fit width, maintaining aspect ratio
                new_height = int(im.height * (STORY_WIDTH / im.width))
                im_resized = im.resize((STORY_WIDTH, new_height), Image.Resampling.LANCZOS)
                
                # Prevent it from taking more than half the screen
                max_img_height = int(STORY_HEIGHT * 0.55)
                if new_height > max_img_height:
                    im_resized = ImageOps.fit(im, (STORY_WIDTH, max_img_height), Image.Resampling.LANCZOS)
                    new_height = max_img_height
                    
                story_img.paste(im_resized, (0, 0))
                y_text_start = new_height + 50
        else:
            y_text_start = 100
            
        # Draw Text
        with Pilmoji(story_img) as pilmoji:
            try:
                font_bold = ImageFont.truetype(os.path.join(FONTS_DIR, "Roboto-Bold.ttf"), 55)
                font_regular = ImageFont.truetype(os.path.join(FONTS_DIR, "Roboto-Regular.ttf"), 45)
                font_small = ImageFont.truetype(os.path.join(FONTS_DIR, "Roboto-Bold.ttf"), 38)
            except Exception:
                logger.warning("Could not load custom fonts, using default.")
                font_bold = ImageFont.load_default()
                font_regular = ImageFont.load_default()
                font_small = ImageFont.load_default()

            margin = 60
            y = y_text_start
            
            # Helper function to draw wrapped text
            def draw_wrapped_text(text, font, max_width_chars, y_pos, x_pos, color=(255, 255, 255)):
                if not text: return y_pos
                raw_lines = text.split('\n')
                for r_line in raw_lines:
                    r_line = r_line.strip()
                    if not r_line:
                        y_pos += int(font.size * 0.5)
                        continue
                    lines = textwrap.wrap(r_line, width=max_width_chars)
                    for line in lines:
                        pilmoji.text((x_pos, y_pos), line, font=font, fill=color)
                        y_pos += font.size + 15
                return y_pos

            # Draw Date
            date_title = f"Proposte del {date_str}"
            pilmoji.text((margin, y), date_title, font=font_bold, fill=(255, 255, 255))
            y += font_bold.size + 40
            
            # Draw Events
            for ev in events:
                sys_str = f" ({ev.get('system')})" if ev.get('system') else ""
                
                booked = int(ev.get('booked_seats', 0) or 0)
                max_s = ev.get('max_seats')
                
                if ev.get('status') == 'cancelled':
                    if max_s is None:
                        seats_display = "0 (Nessun limite)"
                    else:
                        seats_display = f"0/{max_s}"
                    text_line = f"❌ {ev.get('title')}{sys_str} : {seats_display} [ANNULLATO]"
                    color = (255, 100, 100)
                else:
                    if max_s is None:
                        seats_display = "Nessun limite" if booked == 0 else f"Nessun limite (Prenotati: {booked})"
                    else:
                        max_s = int(max_s)
                        avail = max_s - booked
                        if avail <= 0:
                            seats_display = f"0/{max_s} Completo"
                        else:
                            seats_display = f"{avail}/{max_s}"
                    text_line = f"• {ev.get('title')}{sys_str} : {seats_display}"
                    color = (220, 220, 220)
                
                char_width_val = int((STORY_WIDTH - margin * 2) / (font_regular.size * 0.55))
                y = draw_wrapped_text(text_line, font_regular, char_width_val, y, margin, color=color)
                y += 20
                    
            # Draw bottom footer
            footer = "Ci vediamo alle 20:45, alla Gilda del Grifone in Via Ada Negri 8/A, Torino!"
            char_width_footer = int((STORY_WIDTH - margin * 2) / (font_small.size * 0.55))
            
            # Always place footer near the bottom
            y_footer = STORY_HEIGHT - 200
            # If the events list is very long and pushes past the footer, let it override or just use the current y
            if y > y_footer - 50:
                y_footer = y + 50
                
            draw_wrapped_text(footer, font_small, char_width_footer, y_footer, margin, color=(255, 200, 100))

        # Save
        daily_dir = get_daily_dir(output_dir, date_str)
        filename = f"recap_story_{uuid.uuid4()}.jpg"
        filepath = os.path.join(daily_dir, filename)
        story_img.save(filepath, quality=90)
        return filepath
        
    except Exception as e:
        logger.error(f"Error creating recap story image: {e}")
        return None
