import os
import sys

# This test is manual. You'll have to verify the results manually.

# NOTE: Change this if you want to run this script.
user = "kk"

cd = os.path.dirname(os.path.abspath(__file__))
os.chdir(cd)

sys.path.append(os.path.join(cd, "../../src/."))

from decman import Directory, File

# if os.path.exists("/tmp/decman-files"):
#    shutil.rmtree("/tmp/decman-files")
# os.makedirs("/tmp/decman-files")

f1 = File(source_file="src/f1.txt")
f1.copy_to(
    "/tmp/decman-files/f1.txt",
    variables={"%variable%": "123", "%another_variable%": "456"},
)

f2 = File(source_file="src/f2.sh", permissions=0o744)
f2.copy_to(
    "/tmp/decman-files/f2.sh",
)

f3 = File(content="%variable% doesn't work here.", bin_file=True)
f3.copy_to(
    "/tmp/decman-files/f3.txt",
    variables={
        "%variable%": "123",
    },
)

f4 = File(content="%variable% works here.", bin_file=False, owner=user)
f4.copy_to(
    "/tmp/decman-files/f4.txt",
    variables={
        "%variable%": "123",
    },
)

f5 = File(content="%variable% works here.", bin_file=False, owner=user, group="root")
f5.copy_to(
    "/tmp/decman-files/f5.txt",
    variables={
        "%variable%": "123",
    },
)

d = Directory("src/srcdir", bin_files=True)
d.copy_to("/tmp/decman-files/targetdir")
