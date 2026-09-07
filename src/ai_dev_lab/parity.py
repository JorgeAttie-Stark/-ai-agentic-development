def is_even(number):
    # bool herda de int: sem este guarda, True passaria a validação e seria reportado como ímpar.
    if isinstance(number, bool) or not isinstance(number, int):
        raise TypeError(f"is_even espera int, recebeu {type(number).__name__}")
    return number % 2 == 0
