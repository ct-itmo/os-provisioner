import bcrypt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from wtforms.fields import IntegerField, PasswordField
from wtforms.validators import InputRequired, ValidationError

from quirck.auth.model import User
from quirck.core.form import QuirckForm

import osp.model  # pyright: ignore


class PasswordLoginForm(QuirckForm):
    login = IntegerField("Логин", validators=[InputRequired()])
    password = PasswordField("Пароль", validators=[InputRequired()])

    async def async_validate_password(self, password: PasswordField) -> None:
        session: AsyncSession = self._request.scope["db"]

        target_user = (await session.scalars(select(User).where(User.id == self.login.data))).one_or_none()
        
        if target_user is None:
            raise ValidationError("Логин или пароль неверен")
        
        if not bcrypt.checkpw(password.data.encode(), target_user.password.encode()):  # type: ignore
            raise ValidationError("Логин или пароль неверен")
