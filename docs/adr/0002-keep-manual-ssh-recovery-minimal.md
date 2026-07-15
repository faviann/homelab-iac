# Keep manual SSH recovery independent of full contract compilation

Manual SSH recovery validates only the identity and public key needed to restore access to an existing LXC, then uses the same guest-bootstrap implementation as normal lifecycle execution. It must not require the full compiled LXC contract because unrelated invalid infrastructure state could otherwise block the recovery operation.
