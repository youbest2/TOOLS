npp_save
CD C:\MinGW\bin\
g++ "$(FULL_CURRENT_PATH)" -o "$(CURRENT_DIRECTORY)\$(NAME_PART).exe"
cmd /c "$(CURRENT_DIRECTORY)\$(NAME_PART).exe"
