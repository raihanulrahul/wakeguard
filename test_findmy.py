"""Manual phone test, not an automated test. Use the isolated phone environment."""
if __name__ == "__main__":
    from phone_alarm_findmy import main
    import sys
    sys.argv.append("--interactive")
    raise SystemExit(main())
