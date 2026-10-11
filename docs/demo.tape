# Re-record the README demo: `vhs docs/demo.tape` from the repo root with EDGAR_RATIOS_USER_AGENT set
# (live SEC data, a throwaway settings dir).
Output docs/demo.gif

Set Shell zsh
Set FontSize 12
Set Width 1180
Set Height 640
Set Padding 10
Set Framerate 15
Set TypingSpeed 50ms
Set Theme { "background": "#000000", "foreground": "#e0e0e0" }

Hide
Type "export EDGAR_RATIOS_HOME=$(mktemp -d) PATH=$PWD/.venv/bin:$PATH COLUMNS=150 && clear"
Enter
Sleep 1s
Show

# five fiscal years of ratios, straight from Apple's 10-Ks
Type "edgar-ratios AAPL"
Sleep 400ms
Enter
Sleep 9s

Hide
Type "clear"
Enter
Show

# compare each company's latest fiscal year
Type "edgar-ratios MSFT NVDA GOOGL"
Sleep 400ms
Enter
Sleep 10s
