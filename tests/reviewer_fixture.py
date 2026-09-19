"""Prepare inert example source for first-time reviewer sessions; never run it."""
import argparse
from pathlib import Path
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def prepare(destination):
    destination = destination.expanduser().absolute()
    if destination.exists():
        raise ValueError('Choose a new destination; existing directories are left untouched.')
    destination.mkdir(parents=True)
    for source in (ROOT/'example').glob('*.py'):
        shutil.copyfile(source, destination/source.name)
    (destination/'pricing_demo.py').write_text('''def legacy_discount(amount):
    return amount * 0.9

def quoted_total(amount):
    return legacy_discount(amount)

def service_fee(amount):
    return amount * 1.05
''')
    for command in (['init','-q'], ['config','user.email','review-fixture@example.invalid'],
                    ['config','user.name','Threadline review fixture'], ['add','.'], ['commit','-qm','Review baseline']):
        subprocess.run(['git',*command],cwd=destination,check=True)
    (destination/'pricing_demo.py').write_text('''def quoted_total(amount):
    return legacy_discount(amount)

def service_fee(amount):
    return amount * 1.08
''')
    return destination


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('destination', type=Path)
    args = parser.parse_args()
    try:
        destination = prepare(args.destination)
    except ValueError as error:
        parser.error(str(error))
    print(f'Prepared source only: {destination}')
    print(f'threadline review "{destination}" --base HEAD')
