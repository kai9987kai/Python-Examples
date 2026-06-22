from pathlib import Path
import xlsxwriter

LOCATIONS = [
    "ISBT DEHRADUN",
    "SHASTRADHARA",
    "CLEMENT TOWN",
    "RAJPUR ROAD",
    "CLOCK TOWER",
]


def create_location_matrix(output_file: str = "dehradun_location_matrix.xlsx") -> Path:
    """Create a styled, editable Dehradun route/distance matrix workbook."""

    output_path = Path(output_file)

    with xlsxwriter.Workbook(output_path) as workbook:
        worksheet = workbook.add_worksheet("Route Matrix")

        # Workbook metadata
        workbook.set_properties({
            "title": "Dehradun Location Matrix",
            "subject": "Editable route, distance, or travel-time matrix",
            "author": "Python",
        })

        # Formats
        title_format = workbook.add_format({
            "bold": True,
            "font_size": 16,
            "font_color": "#FFFFFF",
            "bg_color": "#1F4E78",
            "align": "center",
            "valign": "vcenter",
        })

        header_format = workbook.add_format({
            "bold": True,
            "font_color": "#FFFFFF",
            "bg_color": "#2F75B5",
            "border": 1,
            "align": "center",
            "valign": "vcenter",
            "text_wrap": True,
        })

        cell_format = workbook.add_format({
            "border": 1,
            "align": "center",
            "valign": "vcenter",
        })

        diagonal_format = workbook.add_format({
            "bold": True,
            "font_color": "#666666",
            "bg_color": "#E7E6E6",
            "border": 1,
            "align": "center",
            "valign": "vcenter",
        })

        note_format = workbook.add_format({
            "italic": True,
            "font_color": "#666666",
        })

        # Layout
        last_col = len(LOCATIONS)
        last_row = len(LOCATIONS) + 1

        worksheet.merge_range(0, 0, 0, last_col, "Dehradun Location Matrix", title_format)
        worksheet.set_row(0, 28)

        # Column and row headers
        worksheet.write(1, 0, "FROM / TO", header_format)
        worksheet.write_row(1, 1, LOCATIONS, header_format)

        for row_index, origin in enumerate(LOCATIONS, start=2):
            worksheet.write(row_index, 0, origin, header_format)

            for col_index, destination in enumerate(LOCATIONS, start=1):
                if origin == destination:
                    worksheet.write(row_index, col_index, 0, diagonal_format)
                else:
                    worksheet.write_blank(row_index, col_index, None, cell_format)

        # Make the sheet practical to use
        worksheet.set_column(0, 0, 24)
        worksheet.set_column(1, last_col, 18)
        worksheet.set_row(1, 38)
        worksheet.set_default_row(22)

        worksheet.freeze_panes(2, 1)
        worksheet.autofilter(1, 0, last_row, last_col)

        # Users can enter route distance or time values.
        worksheet.data_validation(
            2, 1, last_row, last_col,
            {
                "validate": "decimal",
                "criteria": ">=",
                "value": 0,
                "input_title": "Enter a value",
                "input_message": "Enter distance, journey time, or another non-negative numeric value.",
                "error_title": "Invalid value",
                "error_message": "Please enter zero or a positive number.",
            },
        )

        # Visualise higher values automatically.
        worksheet.conditional_format(
            2, 1, last_row, last_col,
            {
                "type": "3_color_scale",
                "min_color": "#C6EFCE",
                "mid_color": "#FFEB9C",
                "max_color": "#FFC7CE",
            },
        )

        worksheet.write(
            last_row + 2,
            0,
            "Enter distances, fares, or travel times in the blank cells. Diagonal cells are set to 0.",
            note_format,
        )

    return output_path


if __name__ == "__main__":
    saved_file = create_location_matrix()
    print(f"Workbook created: {saved_file.resolve()}")
