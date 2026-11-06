"""Immutable template photographs and append-only links."""
from alembic import op
revision="pilot_008"
down_revision="pilot_007"
branch_labels=None
depends_on=None
def upgrade():
    op.execute('\nCREATE TABLE trace_template_photos (\n\tid VARCHAR NOT NULL, \n\tproject_id VARCHAR NOT NULL, \n\tname VARCHAR NOT NULL, \n\tsha256 VARCHAR NOT NULL, \n\tsize INTEGER NOT NULL, \n\tmedia_type VARCHAR NOT NULL, \n\tpath VARCHAR NOT NULL, \n\tcreated_by VARCHAR NOT NULL, \n\tcreated_at VARCHAR NOT NULL, \n\tPRIMARY KEY (id), \n\tFOREIGN KEY(project_id) REFERENCES pilot_projects (id), \n\tFOREIGN KEY(created_by) REFERENCES pilot_accounts (id)\n)\n\n')
    op.execute('\nCREATE TABLE trace_template_photo_links (\n\ttemplate_id VARCHAR NOT NULL, \n\tphoto_id VARCHAR NOT NULL, \n\tactor_id VARCHAR NOT NULL, \n\tat VARCHAR NOT NULL, \n\tPRIMARY KEY (template_id, photo_id), \n\tFOREIGN KEY(template_id) REFERENCES trace_templates (id), \n\tUNIQUE (photo_id), \n\tFOREIGN KEY(photo_id) REFERENCES trace_template_photos (id), \n\tFOREIGN KEY(actor_id) REFERENCES pilot_accounts (id)\n)\n\n')
    op.execute("CREATE TRIGGER trace_template_photos_no_update BEFORE UPDATE ON trace_template_photos BEGIN SELECT RAISE(ABORT,'immutable template photograph'); END")
    op.execute("CREATE TRIGGER trace_template_photos_no_delete BEFORE DELETE ON trace_template_photos BEGIN SELECT RAISE(ABORT,'immutable template photograph'); END")
    op.execute("CREATE TRIGGER trace_template_photo_links_no_update BEFORE UPDATE ON trace_template_photo_links BEGIN SELECT RAISE(ABORT,'immutable template photograph'); END")
    op.execute("CREATE TRIGGER trace_template_photo_links_no_delete BEFORE DELETE ON trace_template_photo_links BEGIN SELECT RAISE(ABORT,'immutable template photograph'); END")
def downgrade():
    raise RuntimeError("照片原件追加留存，恢复使用一致备份")
