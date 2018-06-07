npp_save   
CD C:\MinGW\bin\   
g++ "$(FULL_CURRENT_PATH)" -o "$(CURRENT_DIRECTORY)\$(NAME_PART).exe"   
cmd /c "$(CURRENT_DIRECTORY)\$(NAME_PART).exe"

--
---

NPP_SAVE   
CD $(CURRENT_DIRECTORY)   
D:\Software\codeblocks-16.01mingw-nosetup\MinGW\bin\gcc.exe"$(FILE_NAME)"   
a   
