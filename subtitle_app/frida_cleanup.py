"""Release destroyed wrappers for the bundled, verified Frida binding revision."""


def release_destroyed_script(script):
    # Frida 17.23.3 Script._setup installs native -> bound Python method
    # callbacks; _on_destroyed resolves RPCs but leaves these two references.
    # They keep Script/Condition and user callbacks alive after unload/detach.
    # Only unsubscribe AFTER destruction; never alter callbacks on a live script.
    # Keep this workaround version-gated and covered by repeated-handle tests.
    import frida
    if frida.__version__ != '17.23.3' or not isinstance(script, frida.Script):
        return
    if not script.is_destroyed:
        return
    for signal, callback in (('message', script._on_message), ('destroyed', script._on_destroyed)):
        script._impl.off(signal, callback)
