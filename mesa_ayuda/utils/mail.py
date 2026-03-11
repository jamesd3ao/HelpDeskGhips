import smtplib
from email.message import EmailMessage

def send_mail_with_pdf(*, to_addr: str, subject: str, body: str, filename: str, pdf_bytes: bytes, app):
    if not to_addr:
        raise ValueError("Falta destinatario (to_addr)")

    msg = EmailMessage()
    sender = app.config.get("MAIL_DEFAULT_SENDER") or app.config.get("MAIL_USERNAME")
    if not sender:
        raise RuntimeError("MAIL_DEFAULT_SENDER o MAIL_USERNAME no configurado")

    msg["Subject"] = subject
    msg["From"] = sender
    msg["To"] = to_addr
    msg.set_content(body)
    msg.add_attachment(pdf_bytes, maintype="application", subtype="pdf", filename=filename)

    server = app.config.get("MAIL_SERVER", "smtp.office365.com")
    port = int(app.config.get("MAIL_PORT", 587))
    use_tls = bool(app.config.get("MAIL_USE_TLS", True))
    user = app.config.get("MAIL_USERNAME")
    pwd  = app.config.get("MAIL_PASSWORD")

    if not (user and pwd):
        raise RuntimeError("Faltan credenciales SMTP (MAIL_USERNAME/MAIL_PASSWORD)")

    with smtplib.SMTP(server, port) as smtp:
        if use_tls:
            smtp.starttls()
        smtp.login(user, pwd)
        smtp.send_message(msg)