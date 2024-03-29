import pygsheets
from pygsheets import DataRange, Cell, GridRange

from typing import Optional, List, Dict
from datetime import datetime, timedelta

from ..dataTypes.classes import (
    MeetingTime,
    Attendance,
    AttendancePoll,
    UserCreate,
    UserReturn,
    User,
    ForecastJob,
    MeetingSheetEntry,
)

gc = pygsheets.authorize(service_file="config/secrets/g-service.json")


MEETINGS_TO_FORECAST_SHIFT = (-1, 2)
MEETING_TIME_FORMAT = "%m,%d,%Y %H:%M"
MEETING_TIME_FORMAT_SHORT = "%m,%d,%Y"


class AttendanceSheetController:
    def __init__(self):
        self.gc = pygsheets.authorize(service_file="config/secrets/g-service.json")
        self.sh = self.gc.open_by_key("1_RjQocIi4hCZOkZhzQhN-_3efjWivihcLK0ibF29y3Q")
        self.users_sheet = self.sh.worksheet_by_title("Users")
        self.attendance_sheet = self.sh.worksheet_by_title("Attendance")
        self.forecast_sheet = self.sh.worksheet_by_title("Forecast")
        self.meetings_sheet = self.sh.worksheet_by_title("Meetings")
        self.status_sheet = self.sh.worksheet_by_title("Status")

    # Methods to convert the format of the time in the Meetings sheet to a datetime object
    @staticmethod
    def meeting_cell_time_format(cell: Cell) -> datetime:
        time_format = MEETING_TIME_FORMAT
        return datetime.strptime(cell.value, time_format)

    @staticmethod
    def reverse_meeting_cell_time_format(date: datetime) -> str:
        time_format = MEETING_TIME_FORMAT
        return date.strftime(time_format)

    # Get dates from the Meetings sheet based off of the named range "Dates"
    # IMPORTANT TO REMEMBER THIS IN SETUP OF A NEW SHEET!
    def get_dates(self) -> List[List[Cell]]:
        dates_range = self.meetings_sheet.get_named_range(
            "Dates",
        )
        dates = dates_range.cells
        return dates

    # Get the nearest date to the current date
    def get_nearest_date(self, date: datetime = datetime.now()) -> Optional[Cell]:
        dates = self.get_dates()
        actual_dates = []
        for cell in dates[0]:
            if len(cell.value) == 0:
                continue
            date_value = datetime.strptime(cell.value, MEETING_TIME_FORMAT)
            actual_dates.append(cell)
            if date_value > date:
                return cell
        return None

    def get_nearest_datetime(
        self, date: datetime = datetime.now()
    ) -> Optional[datetime]:
        nearest_date = self.get_nearest_date(date)
        if nearest_date is None:
            return None
        return self.meeting_cell_time_format(nearest_date)

    def get_upcoming_meetings(
        self, window: int, date: datetime = datetime.now()
    ) -> List[MeetingSheetEntry]:
        current_date_cell = self.get_nearest_date(date)
        if current_date_cell is None:
            return []
        remaining_meetings = self.meetings_sheet.get_values(
            (current_date_cell.row, current_date_cell.col),
            (current_date_cell.row + 1, current_date_cell.col + window),
            include_tailing_empty=False,
            returnas="cell",
        )
        if remaining_meetings is None or len(remaining_meetings) != 2:
            raise ValueError(
                "Spreadsheet not formatted correctly. Please check the Meetings sheet. There are no start or end rows"
            )

        if len(remaining_meetings[0]) != len(remaining_meetings[1]):
            raise ValueError(
                "Spreadsheet not formatted correctly. Start and End time rows do not match in length."
            )

        start_times = remaining_meetings[0]
        end_times = remaining_meetings[1]
        meeting_times: List[MeetingSheetEntry] = []

        for x in range(len(start_times)):
            start_time = self.meeting_cell_time_format(start_times[x])
            end_time = self.meeting_cell_time_format(end_times[x])
            meeting_times.append(
                MeetingSheetEntry(
                    start=start_time,
                    end=end_time,
                    column=start_times[x].col,
                    row=start_times[x].row,
                )
            )

        return meeting_times

    # Wrapper of get_upcoming_meetings to get the next week of meetings
    def get_upcoming_week_meetings(
        self, date: datetime = datetime.now()
    ) -> List[MeetingSheetEntry]:
        # Find the number of meeting entries until the next week
        current_date_cell = self.get_nearest_date(date)
        if current_date_cell is None:
            return []
        next_week = date + timedelta(days=7)
        next_week_cell = self.get_nearest_date(next_week)
        if next_week_cell is None:
            return []
        return self.get_upcoming_meetings(
            next_week_cell.col - current_date_cell.col, date
        )

    def get_user(self, user: UserCreate) -> Optional[UserReturn]:
        search = self.users_sheet.find(user.email)
        if len(search) != 0:
            row = search[0].row
            first = self.users_sheet.get_value((row, 2))
            last = self.users_sheet.get_value((row, 3))
            return UserReturn(user.email, row, first, last)
        return None
        # return self.users_sheet.find(user.email, in_column=1, matchEntireCell=True)

    def translate_date_column(self, date: datetime) -> Optional[int]:
        cell = self.meetings_sheet.find(date.strftime(MEETING_TIME_FORMAT))
        if len(cell) == 0:
            return None
        return cell[0].col + MEETINGS_TO_FORECAST_SHIFT[1]

    def get_forecast_entry(self, user: UserReturn, date: datetime) -> Optional[Cell]:
        column = self.translate_date_column(date)
        if column == None:
            print("Column is None!")
            return None
        return self.forecast_sheet.cell((user.row, column))

    def get_user_attendances(self, user: UserReturn) -> List:
        return self.attendance_sheet.get_row(user.row, include_tailing_empty=False)[2:]

    def get_user_forecasts(self, user: UserReturn) -> List:
        return self.forecast_sheet.get_row(user.row, include_tailing_empty=False)[2:]

    def get_attendance_poll(
        self, user: UserReturn, window: int, date: datetime = datetime.now()
    ) -> Optional[AttendancePoll]:
        user = self.get_user(user)
        if user is None:
            return None
        upcoming_meetings = self.get_upcoming_meetings(window, date)

        if len(upcoming_meetings) == 0:
            return None

        # Hard coded optimization so we can avoid another search API Call (which is O(n))
        # Assumes that the meetings are sorted!
        first_column = upcoming_meetings[0].column + MEETINGS_TO_FORECAST_SHIFT[1]
        last_column = upcoming_meetings[-1].column + MEETINGS_TO_FORECAST_SHIFT[1]

        forecast_range = self.forecast_sheet.get_values(
            (user.row, first_column),
            (user.row, last_column),
            include_tailing_empty=False,
            returnas="cell",
        )
        attendances = []
        for i in range(len(upcoming_meetings)):

            meetingCellSheet = upcoming_meetings[i]

            # Map spreadsheet values to python booleans
            attendance_state = True if forecast_range[0][i].value == "TRUE" else False

            attendance = Attendance(
                meetingTime=meetingCellSheet, attendance=attendance_state
            )
            attendances.append(attendance)

        returnUser = User(user.email, user.first, user.last)
        attendancePoll = AttendancePoll(attendances, returnUser)
        return attendancePoll

    def add_user(self, user: User) -> UserReturn:
        first_col = self.users_sheet.get_col(1, include_tailing_empty=False)
        blank_row = len(first_col) + 1
        self.users_sheet.update_row(blank_row, [user.email, user.first, user.last])
        return self.get_user(user)

    # Both checks for user and adds user if not exist
    def lookup_or_add_user(self, user: User) -> UserReturn:
        searched_user = self.get_user(user)  # Check if user exists
        if searched_user is None:
            return self.add_user(user)
        else:
            return searched_user

    def get_row_of_date(self, date: datetime) -> int:
        dates = self.status_sheet.get_col(1, include_tailing_empty=False)

        row = None
        for index, entry in enumerate(dates):
            try:
                if entry == datetime.strftime(date, MEETING_TIME_FORMAT_SHORT):
                    row = index + 1
                    break
            except ValueError:
                print("malformed column")

        return row

    def get_success(self, date: datetime) -> tuple:
        dates = self.status_sheet.get_col(1, include_tailing_empty=False)
        row = None

        td = timedelta((12 - date.weekday()) % 7)
        next_saturday = date + td

        row = self.get_row_of_date(next_saturday)

        if row is None:
            new_index = len(dates) + 1
            self.set_success(next_saturday, False, False, new_index)
            return False, False

        else:
            forecast_status = (
                False if self.status_sheet.get_value(f"B{row}") == "FALSE" else True
            )
            attendance_status = (
                False if self.status_sheet.get_value(f"C{row}") == "FALSE" else True
            )
            return forecast_status, attendance_status

    def set_success(
        self, date: datetime, forecast_status: bool, attendance_status: bool, index=None
    ) -> tuple:
        if index is None:
            index = self.get_row_of_date(date)
        self.status_sheet.update_value(
            f"A{index}", date.strftime(MEETING_TIME_FORMAT_SHORT)
        )
        self.status_sheet.update_value(f"B{index}", f"={forecast_status}")
        self.status_sheet.update_value(f"C{index}", f"={attendance_status}")
        return True

    ## Update the forecast sheet with the attendance poll
    ## THIS FUNCTION IS SOOOOOO SLOW. USE BATCH UPDATE FORECAST INSTEAD!!!
    # def update_forecast(self, poll: AttendancePoll):
    #     user = self.lookup_add_user(poll.user)  # Check if user exists, add them if not
    #     first_entry = self.get_forecast_entry(
    #         user, poll.attendances[0].meetingTime.start
    #     )
    #     starting_column = first_entry.col
    #     self.forecast_sheet.update_row(
    #         user.row,
    #         [attendance.attendance for attendance in poll.attendances],
    #         starting_column,
    #     )
    #     return True

    # Custom batch update for cells
    def batch_update_forecast(self, jobs: Dict[User, ForecastJob]):
        # Jobs will contain a dictionary of users and their forecast jobs
        for user, job in jobs.items():
            column = job.starting_column

            # Update the cells with the values in the poll
            def dynamic_value_format(value: bool) -> dict:
                return [{"userEnteredValue": {"boolValue": value}}]

            # Custom request to update cells based off (https://developers.google.com/sheets/api/reference/rest/v4/spreadsheets/batchUpdate)
            values = [
                dynamic_value_format(attendance.attendance)
                for attendance in job.poll.attendances
            ]

            # Note: The index is 0 based, so the first row is 0, the second row is 1, etc.
            # Thus we need to subtract 1 from the indexes
            custom_request = {
                "updateCells": {
                    "rows": {"values": values},
                    "range": {
                        "sheetId": self.forecast_sheet.id,
                        "startRowIndex": user.row - 1,
                        "endRowIndex": user.row,
                        "startColumnIndex": column - 1,
                        "endColumnIndex": column - 1 + len(job.poll.attendances),
                    },
                    "fields": "userEnteredValue",
                },
            }

            # Run the custom request
            self.sh.custom_request(custom_request, fields="replies")

        return True

    # Grabs the forecasts for a certain window for all users in the sheet
    def get_all_forecasts(
        self,
        # users: List[User],
        window: int = 1,
        date: Optional[datetime] = datetime.now(),
    ) -> Optional[Dict[User, AttendancePoll]]:
        rang = GridRange.create(data=((0, 0), (None, None)), wks=self.forecast_sheet)

        # Get the entire sheet
        forecast_sheet = self.forecast_sheet.get_values(
            grange=rang,
            # include_tailing_empty=False,
            include_tailing_empty_rows=False,
            returnas="matrix",
        )

        user_sheet = self.users_sheet.get_values(
            grange=rang,
            include_tailing_empty=False,
            include_tailing_empty_rows=False,
            returnas="matrix",
        )

        meeting_range = GridRange.create(
            data=((2, 1), (None, None)), wks=self.meetings_sheet
        )
        meeting_sheet = self.meetings_sheet.get_values(
            grange=meeting_range,
            include_tailing_empty=False,
            include_tailing_empty_rows=False,
            returnas="matrix",
            majdim="COLUMNS",
        )

        forecast_sheet_header = forecast_sheet[0]
        forecast_sheet_header_mapper = {}

        user_sheet_header = user_sheet[0]
        user_sheet_header_mapper = {}

        meeting_sheet_header = meeting_sheet[0]
        meeting_sheet_header_mapper = {}

        for i, header in enumerate(forecast_sheet_header):
            try:
                time_object = datetime.strptime(header, MEETING_TIME_FORMAT)
                header = time_object.strftime(MEETING_TIME_FORMAT_SHORT)
            except ValueError:
                pass
            forecast_sheet_header_mapper[header] = i

        for i, header in enumerate(user_sheet_header):
            user_sheet_header_mapper[header] = i

        for i, header in enumerate(meeting_sheet_header):
            meeting_sheet_header_mapper[header] = i

        ROW_SHIFT = 1  # To make the row indexes match between code and real life. Currently shifts by 1 to avoid 0 indexing.
        FORECASTS_START_COLUMN = 3  # The column where the forecasts start

        meeting_mapper: Dict[datetime, MeetingTime] = {}
        for row, entry in enumerate(meeting_sheet[1:]):
            startTime_raw = entry[meeting_sheet_header_mapper["Start Time"]]
            endTime_raw = entry[meeting_sheet_header_mapper["End Time"]]
            print("RAW:")
            print(startTime_raw, endTime_raw)
            try:
                startTime = datetime.strptime(startTime_raw, MEETING_TIME_FORMAT)
                endTime = datetime.strptime(endTime_raw, MEETING_TIME_FORMAT)
            except Exception as e:
                print("FUCK ME", e)
                startTime = datetime.strptime(startTime_raw, MEETING_TIME_FORMAT)
                endTime = datetime.strptime(endTime_raw, MEETING_TIME_FORMAT)
            # try:
            #     startTime = datetime.strptime(startTime_raw, MEETING_TIME_FORMAT)
            #     endTime = datetime.strptime(endTime_raw, MEETING_TIME_FORMAT)
            # except Exception as e:
            #     print(e)
            #     try:
            #         print(f"AGH 2: {startTime_raw}")
            #         startTime = datetime.strptime(startTime_raw, MEETING_TIME_FORMAT_NO_LEADING_ZERO)
            #         endTime = datetime.strptime(endTime_raw, MEETING_TIME_FORMAT_NO_LEADING_ZERO)
            #     except:
            #         print(f"AGH: {startTime_raw}")
            #         startTime = datetime.strptime(startTime_raw, MEETING_TIME_FORMAT_WITH_SECONDS)
            #         endTime = datetime.strptime(endTime_raw, MEETING_TIME_FORMAT_WITH_SECONDS)
            meetingTime = MeetingTime(start=startTime, end=endTime)
            meeting_mapper[startTime] = meetingTime

        # Users are unique by row
        user_mapper = {}
        for row, entry in enumerate(user_sheet[1:]):
            user_mapper[row + ROW_SHIFT] = User(
                email=entry[user_sheet_header_mapper["Email"]],
                first=entry[user_sheet_header_mapper["First"]],
                last=entry[user_sheet_header_mapper["Last"]],
            )
            if user_mapper[row + ROW_SHIFT] == None:
                del user_mapper[row + ROW_SHIFT]

        forecasts: Dict[User, AttendancePoll] = {}

        if date is None:
            latest_date_index = FORECASTS_START_COLUMN
        else:
            latest_date_raw = self.get_nearest_date(date)
            if latest_date_raw is None:
                print("NO MORE MEETINGS")
                return None
            latest_date = datetime.strptime(latest_date_raw.value, MEETING_TIME_FORMAT)
            print("LATEST DATE IS:", latest_date)
            print("Forecast sheet header is:", forecast_sheet_header_mapper)
            try:
                latest_date_index = forecast_sheet_header_mapper[
                    latest_date.strftime(MEETING_TIME_FORMAT_SHORT)
                ]
            except:
                latest_date_index = forecast_sheet_header_mapper[
                    latest_date.strftime(MEETING_TIME_FORMAT_SHORT)
                ]

        for row, entry in enumerate(forecast_sheet[1:]):
            if (
                entry[forecast_sheet_header_mapper["First"]] == ""
                and entry[forecast_sheet_header_mapper["Last"]] == ""
            ):
                break

            user = user_mapper[row + ROW_SHIFT]

            attendances = []
            for i in range(latest_date_index, latest_date_index + window):
                print(i)
                print("HEADER IS:", forecast_sheet_header[i])
                if forecast_sheet_header[i] == "":
                    break

                date = datetime.strptime(forecast_sheet_header[i], MEETING_TIME_FORMAT)
                # if date not in meeting_mapper:
                #     date = datetime.strptime(
                #         forecast_sheet_header[i], MEETING_TIME_FORMAT_SHORT_NO_LEADING_ZERO
                #     )
                if entry[i] == "":
                    print("ERROR IN VALUE")
                    break

                print("MEETING MAPPER IS")
                print(meeting_mapper)
                meetingTime = meeting_mapper[date]
                status = True if entry[i].upper() == "TRUE" else False
                attendance = Attendance(meetingTime, status)
                attendances.append(attendance)
            print("Attendances are: ", attendances)

            forecasts[user] = AttendancePoll(attendances=attendances, user=user)
        print("COMING OUT OF GET ALL FORECASTS")
        return forecasts

    def get_forecasts_upcoming_week(
        self, date: datetime = datetime.now()
    ) -> Optional[Dict[User, AttendancePoll]]:
        # Find the number of meeting entries until the next week
        current_date_cell = self.get_nearest_date(date)
        if current_date_cell is None:
            return []
        next_week = date + timedelta(days=7)
        next_week_cell = self.get_nearest_date(next_week)

        window = next_week_cell.col - current_date_cell.col
        print("WINDOW IS:", window)
        return self.get_all_forecasts(window=window, date=date)
