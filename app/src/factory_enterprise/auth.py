"""Identities and sessions live in PostgreSQL, never in submitted actor fields."""
import re
import secrets
from datetime import datetime, timezone, timedelta
from argon2 import PasswordHasher
from argon2.exceptions import VerificationError
from psycopg.types.json import Jsonb
from .catalog import digest
from .db import uid

PASSWORDS = PasswordHasher()
ROLES = {'owner', 'engineer', 'reviewer', 'validator', 'knowledge', 'viewer'}

class Auth:
    def __init__(self, db): self.db = db

    def create_user(self, actor, username, display_name, password, admin=False, bootstrap=False):
        if not re.fullmatch(r'[A-Za-z0-9_.-]{3,48}', username) or not str(display_name).strip():
            raise ValueError('用户名需 3–48 位字母数字，且需实名显示名称')
        if len(password) < 12 or len(password) > 256:
            raise ValueError('密码长度需 12–256 字符')
        hashed = PASSWORDS.hash(password)
        with self.db.tx() as c:
            count = c.execute('SELECT count(*) AS n FROM ep_users').fetchone()['n']
            if bootstrap:
                if count: raise PermissionError('首次管理员已创建')
                admin = True
            elif not self.user(c, actor)['admin']:
                raise PermissionError('需要管理员')
            user = {'id': uid('user'), 'username': username, 'display_name': display_name.strip(), 'admin': admin, 'enabled': True}
            c.execute('INSERT INTO ep_users VALUES(%s,%s,%s,%s,%s,true)',
                      (user['id'], username, user['display_name'], hashed, admin))
            self.db.event(c, '', actor or user['id'], 'user.create', {'user_id': user['id']})
            return user

    @staticmethod
    def user(c, user_id):
        row = c.execute('SELECT id,username,display_name,admin,enabled FROM ep_users WHERE id=%s', (user_id,)).fetchone()
        if not row or not row['enabled']: raise PermissionError('用户已停用或不存在')
        return row

    def login(self, username, password):
        with self.db.tx() as c:
            row = c.execute('SELECT * FROM ep_users WHERE username=%s', (username,)).fetchone()
            try:
                if not row or not row['enabled']: raise PermissionError('用户名或密码无效')
                PASSWORDS.verify(row['password_hash'], password)
            except VerificationError:
                raise PermissionError('用户名或密码无效') from None
            token, csrf = secrets.token_urlsafe(36), secrets.token_urlsafe(32)
            c.execute('DELETE FROM ep_sessions WHERE expires<now()')
            c.execute('INSERT INTO ep_sessions VALUES(%s,%s,%s,%s)',
                      (digest(token.encode()), row['id'], csrf, datetime.now(timezone.utc) + timedelta(hours=8)))
            return token, csrf, self.user(c, row['id'])

    def session(self, token):
        with self.db.tx(False) as c:
            row = c.execute('SELECT user_id,csrf FROM ep_sessions WHERE token_hash=%s AND expires>now()',
                            (digest(token.encode()),)).fetchone()
            if not row: raise PermissionError('请登录')
            return {**self.user(c, row['user_id']), 'csrf': row['csrf']}

    def members(self, actor, project, user_id=None, roles=None):
        with self.db.tx(user_id is not None) as c:
            self.require(c, actor, project, {'owner'})
            if user_id is not None:
                self.user(c, user_id)
                if set(roles) - ROLES: raise ValueError('未知岗位权限')
                if 'owner' not in roles:
                    owners=c.execute("SELECT user_id FROM ep_members WHERE project_id=%s AND roles ? 'owner' AND user_id<>%s",(project,user_id)).fetchall()
                    if not owners:raise ValueError('项目必须保留至少一名负责人')
                c.execute('INSERT INTO ep_members VALUES(%s,%s,%s) ON CONFLICT(project_id,user_id) DO UPDATE SET roles=EXCLUDED.roles',
                          (project, user_id, Jsonb(roles)))
                p = self.db.get(c, project, 'project'); p['auth_epoch'] += 1; self.db.put(c, 'project', p)
                self.db.event(c, project, actor, 'membership.update', {'user_id': user_id, 'roles': roles})
            return c.execute('SELECT u.id,u.username,u.display_name,m.roles FROM ep_members m JOIN ep_users u ON u.id=m.user_id WHERE m.project_id=%s', (project,)).fetchall()

    def require(self, c, actor, project, roles=None):
        user = self.user(c, actor)
        row = c.execute('SELECT roles FROM ep_members WHERE project_id=%s AND user_id=%s', (project, actor)).fetchone()
        if not row or (roles and not set(row['roles']).intersection(roles)):
            raise PermissionError('缺少本项目岗位权限')
        return {**user, 'roles': row['roles']}
