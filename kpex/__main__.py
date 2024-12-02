from .kpex_cli import KpexCLI
import sys

if __name__ == '__main__':
    cli = KpexCLI()
    cli.main(sys.argv)
