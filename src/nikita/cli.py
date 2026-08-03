def greet(name: str = "World") -> str:
    return f"Hello, {name}!"


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(prog="nikita")
    parser.add_argument("--name", default="World")
    args = parser.parse_args()
    print(greet(args.name))
