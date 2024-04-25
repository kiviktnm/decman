"""
Errors used by decman.
"""


class UserFacingError(Exception):
    """
    Execution of an important step failed and the program shouldn't continue.
    """

    def __init__(self, user_facing_msg: str):
        self.user_facing_msg = user_facing_msg
