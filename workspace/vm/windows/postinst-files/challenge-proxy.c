#include <stdio.h>
#include <windows.h>
#include <winsvc.h>

#pragma comment(lib, "ws2_32.lib") // Winsock Library
#pragma comment(lib, "advapi32.lib") // Svc

// Note: the 3:1 ratio is required
#define NUM_HANDLES 60
#define MAX_CLIENTS 20

void do_proxy(int sockIndex);
BOOL IsDataAvailable(HANDLE hPipe);
void check_on_pipes();
void exit_service();

void setup_network(int port);

VOID WINAPI SvcCtrlHandler(DWORD dwCtrl);
HANDLE child_handles[NUM_HANDLES];
SOCKET client_socket[20];
fd_set readfds;
SOCKET master;

struct timeval timeval;

#define SVCNAME "challengeproxy"
SERVICE_STATUS ServiceStatus;
SERVICE_STATUS_HANDLE hStatus;
void ServiceMain(int argc, char** argv);
void ControlHandler(DWORD request);
void InitService();


void exit_service() {
      ServiceStatus.dwCurrentState = SERVICE_STOPPED;
      SetServiceStatus (hStatus, &ServiceStatus);
      exit(1);
}

void main(int argc, char** argv) {
  //Start the control dispatcher thread for the service
  SERVICE_TABLE_ENTRY ServiceTable[2];
  ServiceTable[0].lpServiceName = SVCNAME;
  ServiceTable[0].lpServiceProc = (LPSERVICE_MAIN_FUNCTION)ServiceMain;
  ServiceTable[1].lpServiceName = NULL;
  ServiceTable[1].lpServiceProc = NULL;
  StartServiceCtrlDispatcher(ServiceTable);
}

void ServiceMain(int argc, char** argv) {

  hStatus = RegisterServiceCtrlHandler(SVCNAME, SvcCtrlHandler);

  ServiceStatus.dwServiceType = SERVICE_WIN32_OWN_PROCESS; 
  ServiceStatus.dwServiceSpecificExitCode = 0;    

  ServiceStatus.dwCurrentState = SERVICE_START_PENDING;
  SetServiceStatus (hStatus, &ServiceStatus);

  InitService();
  ServiceStatus.dwCurrentState = SERVICE_RUNNING;
  BOOL res = SetServiceStatus (hStatus, &ServiceStatus);

  SOCKET new_socket, s;
  struct sockaddr_in address;
  int activity, addrlen, valread;
  addrlen = sizeof(struct sockaddr_in);
  char buffer[0x1000];

  while (TRUE) {
    // clear the socket set
    FD_ZERO(&readfds);

    // add master socket to set
    FD_SET(master, &readfds);
    int max_sd = master;

    // add child sockets to set
    for (int i = 0; i < MAX_CLIENTS; i++) {
      // socket descriptor
      s = client_socket[i];

      // if valid socket descriptor then add to read list
      if (s > 0)
        FD_SET(s, &readfds);

      // highest file descriptor number, need it for the select function
      if (s > max_sd)
        max_sd = s;
    }

    // wait for an activity on one of the sockets, timeout is NULL, so wait
    // indefinitely
    activity = select(max_sd + 1, &readfds, NULL, NULL, &timeval);
    check_on_pipes();

    if ((activity < 0) && (errno != EINTR)) {
      printf("select error");
      exit_service();
    }

    // If something happened on the master socket, then its an incoming
    // connection
    if (FD_ISSET(master, &readfds)) {
      if ((new_socket = accept(master, (struct sockaddr *)&address,
                               (int *)&addrlen)) < 0) {
        perror("accept");
	exit_service();
      }
      // printf("New connection, socket fd is %d, ip is : %s, port : %d \n",
      // (int) new_socket, inet_ntoa(address.sin_addr),
      // ntohs(address.sin_port));

      // add new socket to array of sockets
      for (int i = 0; i < MAX_CLIENTS; i++) {
        // if position is empty
        if (client_socket[i] == 0) {
          client_socket[i] = new_socket;
          do_proxy(i);
          break;
        }
      }
    }

    // else its some IO operation on some other socket
    for (int i = 0; i < MAX_CLIENTS; i++) {
      s = client_socket[i];

      if (FD_ISSET(s, &readfds)) {
        // Check if it was for closing, and also read the incoming message
        if ((valread = recv(s, buffer, 1024, 0)) == 0) {
          // Somebody disconnected, get his details and print
          getpeername(s, (struct sockaddr *)&address, (int *)&addrlen);
          // printf("Host disconnected, ip %s , port %d \n" ,
          // inet_ntoa(address.sin_addr) , ntohs(address.sin_port));

          // Close the socket and mark as 0 in list for reuse
          closesocket(s);
          client_socket[i] = 0;
        }

        // Echo back the message that came in
        else {
          HANDLE child_stdin = child_handles[i * 3];
          WriteFile(child_stdin, buffer, valread, NULL, NULL);
        }
      }
    }
  }
  closesocket(s);
  WSACleanup();
}

void do_proxy(int sockIndex) {
  HANDLE g_hChildStd_IN_Rd = NULL;
  HANDLE g_hChildStd_IN_Wr = NULL;
  HANDLE g_hChildStd_OUT_Rd = NULL;
  HANDLE g_hChildStd_OUT_Wr = NULL;
  HANDLE g_hChildStd_ERR_Rd = NULL;
  HANDLE g_hChildStd_ERR_Wr = NULL;

  char *challenge_needle = "Y:\\*.exe";
  char challenge_path[256];
  WIN32_FIND_DATA find_data;

  PROCESS_INFORMATION piProcInfo;
  STARTUPINFO siStartInfo;

  SECURITY_ATTRIBUTES saAttr;

  // Set the bInheritHandle flag so pipe handles are inherited
  saAttr.nLength = sizeof(SECURITY_ATTRIBUTES);
  saAttr.bInheritHandle = TRUE;
  saAttr.lpSecurityDescriptor = NULL;

  // Create a pipe for the child process's STDOUT
  if (!CreatePipe(&g_hChildStd_OUT_Rd, &g_hChildStd_OUT_Wr, &saAttr, 0))
    puts("Error: Stdout CreatePipe");

  // Ensure the read handle to the pipe for STDOUT is not inherited
  SetHandleInformation(g_hChildStd_OUT_Rd, HANDLE_FLAG_INHERIT, 0);

  // Create a pipe for the child process's STDERR
  if (!CreatePipe(&g_hChildStd_ERR_Rd, &g_hChildStd_ERR_Wr, &saAttr, 0))
    puts("Stderr CreatePipe");

  // Ensure the read handle to the pipe for STDERR is not inherited
  SetHandleInformation(g_hChildStd_ERR_Rd, HANDLE_FLAG_INHERIT, 0);

  // Create a pipe for the child process's STDIN
  if (!CreatePipe(&g_hChildStd_IN_Rd, &g_hChildStd_IN_Wr, &saAttr, 0))
    puts("Stdin CreatePipe");

  // Ensure the write handle to the pipe for STDIN is not inherited
  SetHandleInformation(g_hChildStd_IN_Wr, HANDLE_FLAG_INHERIT, 0);

  ZeroMemory(&piProcInfo, sizeof(PROCESS_INFORMATION));
  ZeroMemory(&siStartInfo, sizeof(STARTUPINFO));
  siStartInfo.cb = sizeof(STARTUPINFO);
  siStartInfo.hStdError = g_hChildStd_ERR_Wr;
  siStartInfo.hStdOutput = g_hChildStd_OUT_Wr;
  siStartInfo.hStdInput = g_hChildStd_IN_Rd;
  siStartInfo.dwFlags |= STARTF_USESTDHANDLES;

  FindFirstFile(challenge_needle, &find_data);
  // Create the child process

  sprintf(challenge_path, "Y:\\%s", find_data.cFileName);

  BOOL bSuccess =
      CreateProcessA(NULL,
                     challenge_path,  // Command line
                     NULL,                 // Process handle not inheritable
                     NULL,                 // Thread handle not inheritable
                     TRUE,                 // Set handle inheritance to TRUE
                     0,                    // No creation flags
                     NULL,                 // Use parent's environment block
                     NULL,                 // Use parent's starting directory
                     &siStartInfo,         // Pointer to STARTUPINFO structure
                     &piProcInfo); // Pointer to PROCESS_INFORMATION structure

  if (!bSuccess) {
    puts("CreateProcess");
    exit_service();
  } else {
    // Add the pipes to the list
    // second socket, i = 1
    // handles 3, 4, 5 = stdin, stdout, stderr
    child_handles[sockIndex * 3] = g_hChildStd_IN_Wr;
    child_handles[sockIndex * 3 + 1] = g_hChildStd_OUT_Rd;
    child_handles[sockIndex * 3 + 2] = g_hChildStd_ERR_Rd;

    // Close handles to the stdin and stdout pipes no longer needed by the child
    // process If they are not explicitly closed, there is no way to recognize
    // that the child process has ended
    CloseHandle(g_hChildStd_OUT_Wr);
    CloseHandle(g_hChildStd_ERR_Wr);
    CloseHandle(g_hChildStd_IN_Rd);
  }
}

BOOL IsDataAvailable(HANDLE hPipe) {
  DWORD bytesAvailable = 0;
  BOOL success = PeekNamedPipe(hPipe, NULL, 0, NULL, &bytesAvailable, NULL);
  if (!success) {
    return FALSE;
  }
  return bytesAvailable > 0;
}

void check_on_pipes() {
  // Handles the Challenge -> Socket data routing

  HANDLE target;
  char buf[0x1000];
  DWORD bytes_read;

  for (int i = 0; i < NUM_HANDLES; i += 3) {
    target = child_handles[i + 1];
    if (IsDataAvailable(target)) {
      SOCKET socket = client_socket[i / 3];
      ReadFile(target, buf, 0x1000, &bytes_read, NULL);
      send(socket, buf, bytes_read, 0);
    }
    target = child_handles[i + 2];
    if (IsDataAvailable(target)) {
      SOCKET socket = client_socket[i / 3];
      ReadFile(target, buf, 0x1000, &bytes_read, NULL);
      send(socket, buf, bytes_read, 0);
    }
  }
}

void InitService() {
  WSADATA wsa;
  struct sockaddr_in server;

  // initialise all client_socket[] to 0 so not checked
  for (int i = 0; i < MAX_CLIENTS; i++)
    client_socket[i] = 0;

  for (int i = 0; i < MAX_CLIENTS * 3; i++)
    child_handles[i] = 0;

  // Initialize timeval
  timeval.tv_sec = 0;
  timeval.tv_usec = 1000;

  // Initialise Winsock
  if (WSAStartup(MAKEWORD(2, 2), &wsa) != 0) {
    printf("Failed. Error Code : %d", WSAGetLastError());
    exit_service();
  }

  // Create a socket
  if ((master = socket(AF_INET, SOCK_STREAM, 0)) == INVALID_SOCKET) {
    printf("Could not create socket : %d", WSAGetLastError());
    exit_service();
  }

  // Prepare the sockaddr_in structure
  server.sin_family = AF_INET;
  server.sin_addr.s_addr = INADDR_ANY;
  server.sin_port = htons(4001);

  // Bind
  if (bind(master, (struct sockaddr *)&server, sizeof(server)) ==
      SOCKET_ERROR) {
    printf("Bind failed with error code : %d", WSAGetLastError());
    exit_service();
  }

  // Listen to incoming connections
  listen(master, 3);
  printf("Waiting for incoming connections...\n");
}

VOID WINAPI SvcCtrlHandler( DWORD dwCtrl ) {
   // Handle the requested control code. 

   switch(dwCtrl) {  
      case SERVICE_CONTROL_STOP: 
	 exit_service();
         return;
 
      case SERVICE_CONTROL_INTERROGATE: 
         break; 
 
      default: 
         break;
   } 
   
}
