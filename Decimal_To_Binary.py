'''
PYTHON 3
Author: Sandeep Pillai (www.github.com/Corruption13)

Program: Decimal to Binary converter.

This program accepts fractional and negative values, and converts them to binary.
'''
decimal_accuracy = 7


def dtbconverter(num):      # Function inputs a float value and returns a list as output
                            # Reasoning for list instead of integer: to avoid integer overflow error.
    is_negative = num < 0
    num = abs(num)

    whole = []                                   # The part before decimal point
    fractional = ['.']                          # The part after decimal point

    decimal = round(num % 1, decimal_accuracy)    # Extract fractional number part of decimal
    w_num = int(num)                            # Extract whole number part of decimal.

    i = 0     # Some fractional decimal numbers have infinite binary values, so we limit this loop below.

    # Loop to find binary of decimal part
    while decimal != 0 and i < decimal_accuracy:
        decimal = decimal * 2
        fractional.append(int(decimal // 1))
        decimal = round(decimal % 1, decimal_accuracy)
        i = i + 1

    # If no fractional part, append '0'
    if len(fractional) == 1:
        fractional.append(0)

    # Loop to find binary of whole number part.
    if w_num == 0:
        whole.append(0)
    else:
        while w_num != 0:
            whole.append(w_num % 2)
            w_num = w_num // 2
        whole.reverse()

    result = whole + fractional
    if is_negative:
        result.insert(0, '-')
    return result


# Test lines.
try:
    number = float(input("Enter ANY base-10 Number: "))
    binary_list = dtbconverter(number)
    print("The Binary Equivalent: " + "".join(map(str, binary_list)))
except ValueError:
    print("Please enter a valid decimal number.")

