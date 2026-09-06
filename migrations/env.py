from logging.config import fileConfig
import os
from alembic import context
from sqlalchemy import engine_from_config,pool

config=context.config
config.set_main_option('sqlalchemy.url',os.environ['DATABASE_URL'])
if config.config_file_name:fileConfig(config.config_file_name)
target_metadata=None
def offline():context.configure(url=config.get_main_option('sqlalchemy.url'),literal_binds=True);context.run_migrations()
def online():
    with engine_from_config(config.get_section(config.config_ini_section),prefix='sqlalchemy.',poolclass=pool.NullPool).connect() as connection:
        context.configure(connection=connection,target_metadata=target_metadata)
        with context.begin_transaction():context.run_migrations()
offline() if context.is_offline_mode() else online()
