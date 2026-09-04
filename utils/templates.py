import html

def format_public_event_message(event_data):
    booked = int(event_data.get('booked_seats', 0) or 0)
    max_s = event_data.get('max_seats')
    status = event_data.get('status', 'pending')
    
    if status == 'cancelled':
        if max_s is None:
            posti = "0 (Nessun limite) [ANNULLATO]"
        else:
            posti = f"0/{max_s} [ANNULLATO]"
        title = f"❌ [ANNULLATO] {event_data.get('title', 'Evento')}"
    else:
        if max_s is None:
            if booked > 0:
                posti = f"Nessun limite (Prenotati: {booked})"
            else:
                posti = "Nessun limite"
        else:
            max_s = int(max_s)
            avail = max_s - booked
            if avail <= 0:
                posti = f"0/{max_s} Completo"
            else:
                posti = f"{avail}/{max_s}"
        title = f"{event_data.get('title', 'Evento')}"
        
    extra = (event_data.get('extra_info') or '').strip()
    extra_block = f"\n🏷️ **Dettagli:**\n{extra}\n" if extra else ""

    desc = (event_data.get('description') or '').strip()
    desc_block = f"\n📝 {desc}" if desc else ""

    return (
        f"📣 **{title}**\n"
        f"📅 Data: {event_data.get('date', 'N/A')}\n"
        f"🎲 Sistema: {event_data.get('system', 'N/A')}\n"
        f"👑 Master: {event_data.get('host') or 'N/A'}\n"
        f"🪑 Posti: {posti}\n"
        f"{extra_block}"
        f"{desc_block}"
    )

def format_instagram_story(event_data):
    max_s = event_data.get('max_seats')
    
    if max_s is None:
        posti = "Nessun limite"
    else:
        posti = str(max_s)

    host = event_data.get('host') or 'N/A'
    extra = (event_data.get('extra_info') or '').strip()
    extra_block = f"\n🏷️ Dettagli:\n{extra}\n" if extra else ""
    desc = (event_data.get('description') or '').strip()
    desc_block = f"\n{desc}" if desc else ""

    return (
        f"Titolo: {event_data.get('title', 'N/A')}\n"
        f"Data: {event_data.get('date', 'N/A')}\n"
        f"Sistema: {event_data.get('system', 'N/A')}\n"
        f"Master/Host: {host}\n"
        f"Posti: {posti}\n"
        f"{extra_block}"
        f"{desc_block}"
    )

def recap_generate_text(day_str, date_str, events):
    header = (
        f"Quali sono le proposte della Gilda del Grifone per stasera, {day_str} {date_str}? 🎲\n\n"
        f"Ecco i tavoli in programma! Trovi i link per prenotarti nei commenti qui sotto:\n\n"
    )
    
    body = ""
    for ev in events:
        sys_val = ev.get('system')
        sys_str = f" ({html.escape(sys_val)})" if sys_val else ""
        
        booked = int(ev.get('booked_seats', 0) or 0)
        max_s = ev.get('max_seats')
        
        if max_s is None:
            seats_display = f"Nessun limite (Prenotati: {booked})"
        else:
            max_s = int(max_s)
            avail = max_s - booked
            if avail <= 0:
                seats_display = f"0/{max_s} Completo"
            else:
                seats_display = f"{avail}/{max_s}"
            
        title = html.escape(ev.get('title') or 'Evento')
            
        if ev.get('status') == 'cancelled':
            if max_s is None:
                seats_display = "0 (Nessun limite)"
            else:
                seats_display = f"0/{max_s}"
            body += f"- ❌ {title}{sys_str} : {seats_display} [ANNULLATO]\n\n"
        else:
            body += f"- {title}{sys_str} : {seats_display}\n\n"
        
    footer = (
        "Tutto pieno? Vieni lo stesso! Abbiamo oltre 400 giochi a disposizione. "
        "Se invece vuoi proporre tu una serata, contatta @Destard o @ManueleAbi.\n\n"
        "Ci vediamo alle 20:45! 🦅"
    )
    
    full_text = header + body + footer
    
    if len(full_text) > 1024:
        slim_header = (
            f"Proposte di stasera, {day_str} {date_str} 🎲\n"
            f"Trovi i link per prenotarti nei commenti qui sotto:\n\n"
        )
        slim_footer = (
            "\nVuoi proporre una serata? Scrivi a @Destard o @ManueleAbi.\n"
            "Ci vediamo alle 20:45! 🦅"
        )
        return slim_header + body + slim_footer
        
    return full_text



def recap_links_text(events):
    if not events:
        return ""
    text = "🔗 <b>Link agli eventi per prenotarsi:</b>\n\n"
    for ev in events:
        if ev.get('status') == 'cancelled':
            continue
        link = ev.get('message_link')
        title = html.escape(ev.get('title') or 'Evento')
        sys_val = ev.get('system')
        sys_str = f" ({html.escape(sys_val)})" if sys_val else ""
        if link:
            text += f"- <a href='{link}'>{title}</a>{sys_str}\n"
        else:
            text += f"- {title}{sys_str}\n"
    return text
