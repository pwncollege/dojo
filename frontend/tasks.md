# 1. Next challenge 
When we are in workspace and after solving a challenge. We want to be able to start the next challenge. The edge cases is if we are on the last challenge, we want to go to the first resource in next module. If no resources then go to first challenge.

We have /next in our dojo api but you need to understand it and see if it works for us. If not, we can implement the logic ourselves if we have dojo + module data


# 2. Restart in practice or normal mode
Our workspace runs in normal mode by default. We want to be able to switch to practice mode which gives us the root access to the workspace but the solutions and flags won't count towards the score. Check how docker.py does it and how does the normal dojo app does it


# 3. Implement search functionality. 
Search button should open a search modal with search bar and search results. The experience should be super smooth and crisp. It should be keyboard accessible and should work on mobile devices.


# 4. Terminate / Close challenge doesnt work
When we have an active challenge, an active challenge widget is always displayed. However, if we click X to close the challenge, the challenge is not terminated.


# 5. Implement The leaderboard in Dojo details page
Check how the leaderboard is implemented in the normal dojo app. We want to implement the same functionality in our nextjs app but better ;).


# 6. Implement the profile page. 
Check how the profile page is implemented in the normal dojo app. We want to implement the same functionality in our nextjs app but better ;).


# 7. The stats in the dojo cards are not correct
Progress is 0, active hackers are always empty. Also the stats in the course statistics section "HJacking Now" is always 0. Check how the stats are implemented in the normal dojo app.


# 8. The fullscreen state in workspace needs rewrite
Here are the states:
- Normal state: sidebar, workspace header, service area / resource viewer
- Fullscreen Hide sidebar, show workspace header, SHOW ONLY service area and a floating bar at the top. The bar should auto hide to top and leave a small handle and the user can bring it back by hovering over the top 
handle
  - The floating bar should have the same content as the normal resource/service bar. 
  - Similar to the floating handle, we should have a another floating handle on the left that shows a floating bar with the same content as the normal workspace view. 
# IMPOORTANT
- If we are changing something that existed in origin/master YOU HAVE TO ASK ME AND TELL ME THAT THIS IS A CORE CHANGE. The 

- You have to study and understand the core dojo logic before you decide to add or change something. We don't want redundant functionality or verbose + unneeded code

- For any core change, commit it separately and have "core: ..." commit msg
