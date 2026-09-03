def format_public_event_message(event_data):
    booked = int(event_data.get('booked_seats', 0) or 0)
    max_s = event_data.get('max_seats')
    
    if max_s is None:
        posti = f"Nessun limite (Prenotati: {booked})"
    else:
        max_s = int(max_s)
        avail = max_s - booked
        if avail <= 0:
            posti = f"0/{max_s} Completo"
        else:
            posti = f"{avail}/{max_s}"
        
    return (
        f"📣 **{event_data.get('title', 'Evento')}**\n"
        f"📅 Data: {event_data.get('date', 'N/A')}\n"
        f"🎲 Sistema: {event_data.get('system', 'N/A')}\n"
        f"👑 Master: {event_data.get('host', 'N/A')}\n"
        f"🪑 Posti: {posti}\n\n"
        f"📝 {event_data.get('description', '')}"
    )

def format_instagram_story(event_data):
    return (
        f"Titolo: {event_data.get('title', 'N/A')}\n"
        f"Data: {event_data.get('date', 'N/A')}\n"
        f"Sistema: {event_data.get('system', 'N/A')}\n"
        f"Posti: {event_data.get('seats', 'N/A')}\n\n"
        f"{event_data.get('description', '')}"
    )

def generate_recap_text(day_str, date_str, events):
    header = f"Quali sono le proposte della Gilda del Grifone per questa sera, {day_str} {date_str}? \n\nEcco i giochi che portiamo:\nSe siete interessati a partecipare, e ci sono ancora posti, rispondete al messaggio dell'evento associato (guarda sotto i link per risparmiare tempo ed andare subito all'evento).\n\n"
    
    body = ""
    for ev in events:
        sys_str = f" ({ev.get('system')})" if ev.get('system') else ""
        
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
            
        if ev.get('status') == 'cancelled':
            if max_s is None:
                seats_display = "0 (Nessun limite)"
            else:
                seats_display = f"0/{max_s}"
            body += f"- ❌ {ev.get('title')}{sys_str} : {seats_display} [ANNULLATO]\n\n"
        else:
            body += f"- {ev.get('title')}{sys_str} : {seats_display}\n\n"
        
    footer = "Nessuna proposta è soddisfacente o il tavolo è già completo? Puoi venire ugualmente, abbiamo più di 400 giochi nei nostri armadi, oppure proporre tu direttamente una serata, mandandola a @Destard o @ManueleAbi! Qualora i dimostratori avessero necessità di annullare i tavoli per urgenze improvvise, possono segnalarlo ai medesimi.\n\nCi vediamo alle 20:45!"
    
    full_text = header + body + footer
    
    if len(full_text) > 1024:
        # TODO: Define slimmer template if needed
        slim_header = f"Proposte di stasera, {day_str} {date_str}:\n\n"
        slim_footer = "\nCi vediamo alle 20:45!"
        return slim_header + body + slim_footer
        
    return full_text


