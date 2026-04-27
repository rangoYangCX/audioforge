from audioforge.app.controllers.main_controller import MainController


def main() -> int:
    controller = MainController()
    controller.show()
    return controller.run()


if __name__ == "__main__":
    raise SystemExit(main())