"""Reserve normalized registration identities without deleting legacy accounts."""
import re,time
from alembic import op
from sqlalchemy import text
revision='0007_registration_identities'
down_revision='0006_mobile'
branch_labels=None
depends_on=None

def upgrade():
    bind=op.get_bind()
    bind.execute(text('CREATE TABLE registration_identities (id BIGSERIAL PRIMARY KEY,kind TEXT NOT NULL,address TEXT NOT NULL,owner_email TEXT NOT NULL,created_at DOUBLE PRECISION NOT NULL,UNIQUE(kind,address))'))
    rows=list(bind.execute(text('SELECT email,phone_number FROM users')))
    rows.extend(bind.execute(text("SELECT registered_email,phone_number FROM pending_exam_registrations WHERE status IN ('PENDING','LINKED')")))
    claims={}
    for email,phone in rows:
        email=email.strip().lower();digits=re.sub(r'\D','',phone or '')
        if len(digits)==12 and digits.startswith('91'):digits=digits[2:]
        mobile=('+91'+digits if len(digits)==10 else '+'+digits) if digits else ''
        for kind,address in [('EMAIL',email),('PHONE',mobile)]:
            if not address:continue
            previous=claims.get((kind,address),email)
            claims[kind,address]=email if previous==email else '__legacy_conflict__'
    for (kind,address),owner in claims.items():bind.execute(text('INSERT INTO registration_identities(kind,address,owner_email,created_at) VALUES(:kind,:address,:owner,:now)'),{'kind':kind,'address':address,'owner':owner,'now':time.time()})

def downgrade():op.drop_table('registration_identities')
