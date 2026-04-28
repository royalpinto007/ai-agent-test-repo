import subprocess


def ask_claude(prompt):
    result = subprocess.run(
        ["claude", "-p", "--tools", ""],
        input=prompt,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"claude exited {result.returncode}: {result.stderr.strip()}")
    output = result.stdout.strip()
    if output.startswith("```"):
        lines = output.splitlines()
        lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        output = "\n".join(lines)
    return output
