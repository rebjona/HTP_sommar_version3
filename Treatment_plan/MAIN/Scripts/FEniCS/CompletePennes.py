"""

 This code combines Pennes.py with CoolPennes.py, i.e both scaling and time computations are performed.
 It is possible to combine plans, i.e to have a temperature matrix from an earlier P as initial condition to the next P. In order to combine different P they must be named P1, P2,.. etc and put in the folder  Input_to_FEniCS. If only one P is used, then just call it P, no index is needed.
 TODO: implement non-linear parameters for the perfusion.
    
"""

import h5py
import matlab.engine
eng = matlab.engine.start_matlab()
from scipy.io import loadmat

from dolfin import *
import numpy as np

# NON_LINEAR PERFUSION vs CONSTANT PERFUSION
# Define if you want to use the non-linear model(=True) of perfusion or constant values(=False)
non_linear_perfusion=True


# Load .mat parameter
# The optional input argument 'degree' is FEniCS internal interpolation type.
# The loaded data will additionally be fit with trilinear interpolation.
def load_data(filename, degree=0):
    
    # Load the .mat file
    f = h5py.File(filename, "r")
    data = np.array(list(f.items())[0][1], dtype=float)
    f.close()
    
    # Load the intepolation c++ code
    f = open('TheGreatInterpolator.cpp', "r")
    code = f.read()
    f.close()
    
    # Amend axis ordering to match layout in memory
    size = tuple(reversed(np.shape(data)))
    
    # Add c++ code to FEniCS
    P = Expression(code, degree=degree)
    
    # Add parameters about the data
    P.stridex  = size[0]
    P.stridexy = size[0]*size[1]
    P.sizex = size[0]
    P.sizey = size[1]
    P.sizez = size[2]
    P.sidelen = 1.0/1000
    
    # As the last step, add the data
    P.set_data(data)
    return P

# Load mesh
print("Reading and unpacking mesh...")
mesh = Mesh('../Input_to_FEniCS/mesh.xml')

# Define material properties
# ----------------------------------------------------------
# T_b:      blood temperature [K relative body temp]
# P:        power loss density [W/m^3]
# k_tis:    thermal conductivity [W/(m K)]
# w_c_b:    volumetric perfusion times blood heat capacity [W/(m^3 K)]
# alpha:    boundary heat transfer constant [W/(m^2 K)]
# T_out_ht  alpha times ambient temperature [W/(m^2)]

print('Importing material properties...')
# Load P matrices, either just one or several depending on how many HT plans one wants to combine.
P1        = load_data("../Input_to_FEniCS/P.mat")
#P2        = load_data("../Input_to_FEniCS/P1.mat") # add additional plans if wanted
#P3        = load_data("../Input_to_FEniCS/P3.mat")

T_b = Constant(0.0) # Blood temperature relative body temp
k_tis    = load_data("../Input_to_FEniCS/thermal_cond.mat")
#rho= load_data("../Input_to_FEniCS/density.mat")
#c= load_data("../Input_to_FEniCS/heat_capacity.mat")
tissue_mat = loadmat("../Input_to_FEniCS/tissue_mat.mat")
#w = loadmat("../Input_to_FEniCS/perfusion_mat_nonlin.mat") # TODO script för att generera denna

# Load the w_c_b, depending on whether one wants to use linear perfusion data or non-linear perfusion data.
w_c_b    = load_data("../Input_to_FEniCS/perfusion_heatcapacity.mat") # This is the "standard" perfusion matrix with linear values
#w_c_b   = load_data("../Input_to_FEniCS/perfusion_heatcapacity_nonlinear.mat") # TODO This should be chosen if a non-linear scaling of the perfusion is wanted, not created yet though
alpha    = load_data("../Input_to_FEniCS/bnd_heat_transfer.mat", 0)
T_out_ht = load_data("../Input_to_FEniCS/bnd_temp_times_ht.mat", 0)


# Read current amplitudes and the amplitude limit, generated in MATLAB
with open("../Input_to_FEniCS/amplitudes.txt") as file:
    amplitudes = []
    for line in file:
        amplitudes.append(line.rstrip().split(","))

with open("../Input_to_FEniCS/ampLimit.txt") as file:
    ampLimit = []
    for line in file:
        ampLimit.append(line.rstrip().split(","))

# Read model type
with open("../Input_to_FEniCS/modelType.txt") as file:
    modelType=[];
    for line in file:
        modelType.append(line.rstrip())

print(modelType)

print("Done loading.")

# Set parameters
#-----------------------
Tmax= 5 # 0 = 37C, 8 if head and neck, 5 if brain
Tmin= 4.5 # 0 = 37C
maxIter=180

#Change type of data
al=ampLimit[0][0]
ampLimit=float(al)
maxAmpl=max(amplitudes)
maxAmp=maxAmpl[0][0]
maxAmp=int(maxAmpl[0][0])
maxAmp=float(maxAmp)

# Define function space and test/trial functions needed for the variational formulation
V = FunctionSpace(mesh, "CG", 1)
u = TrialFunction(V)
v = TestFunction(V)

numberOfP=1 # insert number of P used, i.e how many plans that should be combined

for i in range(numberOfP): # Outer loop for each HT plan one wants to include

# Perform the scaling iteratively ------------------------------------------------------

   # Load P, it is possible to combine different plans by naming them P1, P2,.. etc and putting them in the folder  Input_to_FEniCS. If only one P is used, then just call it P
    if numberOfP==1:
        P = load_data("../Input_to_FEniCS/P.mat")
    else:
        P= load_data("../Input_to_FEniCS/P" + str(i) + ".mat")
    
    scaleTot=1;
    nbrIter=0;
    T=0
    done=False

    while (((np.max(T)<Tmin or np.max(T)>Tmax) and nbrIter<=maxIter) or maxAmp>ampLimit):
    
        #If amplitude is too high, maxAmp is set to amlitude limit
        if (maxAmp>ampLimit):# and np.max(T)<Tmax):
            print(np.max(T))
            scaleAmp=(ampLimit/maxAmp)**2
            maxAmp=ampLimit
            scaleTot=scaleTot*(scaleAmp)
            P=P*scaleAmp
        
            V = FunctionSpace(mesh, "CG", 1)
            u = TrialFunction(V)
            v = TestFunction(V)
            # Variation formulation of Pennes heat equation
            a = v*u*alpha*ds + k_tis*inner(grad(u), grad(v))*dx + w_c_b*v*u*dx
            L = T_out_ht*v*ds + P*v*dx # + w_c_b*T_b*v*dx not needed due to T_b = 0
        
            u = Function(V)
            solve(a == L, u, solver_parameters={'linear_solver':'gmres'}) #gmres is fast
            T =u.vector().array()
            print("Tmax:")
            print(np.max(T))
            print("Scale:")
            print(scaleTot)
            if (np.max(T)<Tmax):
                done = True # exit loop

        elif (maxAmp<=ampLimit):
            V = FunctionSpace(mesh, "CG", 1)
            u = TrialFunction(V)
            v = TestFunction(V)
            # Variation formulation of Pennes heat equation
            a = v*u*alpha*ds + k_tis*inner(grad(u), grad(v))*dx + w_c_b*v*u*dx
            L = T_out_ht*v*ds + P*v*dx # + w_c_b*T_b*v*dx not needed due to T_b = 0
            u = Function(V)
            solve(a == L, u, solver_parameters={'linear_solver':'gmres'}) #gmres is fast
        
            #Use T to find the scale for P and maxAmp (increase T)
            if(np.max(T)<=Tmin):
                if(np.max(T)<0.4*Tmin):
                    P=P*(1.6)
                    scaleTot=scaleTot*1.6
                    maxAmp=sqrt(1.6)*maxAmp
                elif (np.max(T)>=0.4*Tmin and np.max(T)<0.8*Tmin):
                    P=P*(1.3)
                    scaleTot=scaleTot*1.3
                    maxAmp=sqrt(1.3)*maxAmp
                elif (np.max(T)>=0.8*Tmin):
                    P=P*1.05
                    scaleTot=1.05*scaleTot
                    maxAmp=sqrt(1.05)*maxAmp
            #Use T to find the scale for P and maxAmp (decrease T)
            if(np.max(T)>=Tmax):
                if(np.max(T)>1.4*Tmax):
                    P=P*0.5
                    scaleTot=scaleTot*0.5
                    maxAmp=sqrt(0.5)*maxAmp
                elif(np.max(T)>1.2*Tmax and np.max(T)<=1.4*Tmax):
                    P=P*0.7
                    scaleTot=scaleTot*0.7
                    maxAmp=sqrt(0.7)*maxAmp
                elif (np.max(T)<=1.2*Tmax):
                    P=P*0.85
                    scaleTot=scaleTot*(0.85)
                    maxAmp=sqrt(0.85)*maxAmp

            T =u.vector().array()

        nbrIter=nbrIter+1
        print("Tmax:")
        print(np.max(T))
        print("Scale:")
        print(scaleTot)
        print("MaxAmp:")
        print(maxAmp)
        
        if(done):
            break

    # Save temperature matrix, amplitudes and scale factor
    if ((np.max(T)>Tmin and np.max(T)<Tmax and maxAmp<=ampLimit) or maxAmp==ampLimit):
        
        # Plot solution and mesh
        #plot(u)
        #plot(mesh)
        
        # Save data in a format readable by matlab
        Coords = mesh.coordinates()
        Cells  = mesh.cells()
        
        f = h5py.File('../FEniCS_results/temperature.h5','w')
        
        f.create_dataset(name='Temp', data=T)
        f.create_dataset(name='P',    data=Coords)
        f.create_dataset(name='T',    data=Cells)
        # Need a dof(degree of freedom)-map to permutate Temp
        f.create_dataset(name='Map',  data=dof_to_vertex_map(V))
        
        f.close()
        
        #Scale amplitudes and save in a new file
        amplitudeVec=[]
        fileAmp=open('../FEniCS_results/scaledAmplitudes.txt','w')
        for x in amplitudes:
            a=float(x[0])
            a=(round(a*100))*sqrt(scaleTot)/100
            amplitudeVec.append(a)
            fileAmp.write(str(a) + " ")
        fileAmp.close()
        # Save the scale factor in a file
        fileScale=open('../FEniCS_results/scale_factor.txt','w')
        fileScale.write(str(scaleTot))
        fileScale.close()

        #Print parameters
        print("Tmax:")
        print(np.max(T))
        print("Scale:")
        print(scaleTot)
        print("Nbr of iterations:")
        print(nbrIter)
        print("MaxAmp:")
        print(maxAmp)
        
        if (np.max(T)>Tmax and ampLimit==maxAmp):
            print(" High temperature. Try to increase the interval [Tmin,Tmax] or try a higher maxIter.")

    else:
        print("Not enough iterations for the scaling")

    print("Scaling finished")

    #-----------------------------------------------------------------------------------------
    # Reset variables
    del v, T, P, V
    if numberOfP==1:
        P = load_data("../Input_to_FEniCS/P.mat")
    else:
        P= load_data("../Input_to_FEniCS/P" + str(i) + ".mat")

    # Perform the time calculations as in CoolPennes------------------------------------------

    #if non_linear_perfusion
    #         engine.create_initial_perf_nonlin(tissue_mat, w, modelType)
    #         w= loadmat("../Input_to_FEniCS/initial_perf.mat")
    #           

    Time=1
    dt=0.1
    numSteps=Time/dt
    scale=scaleTot
    print("Scale is:")
    print(scale)

    # Define function space and test/trial functions needed for the variational formulation
    V = FunctionSpace(mesh, "CG", 1)
    u = TrialFunction(V)
    v = TestFunction(V)

    if i==0:
        #Initial condition, should only be used for the first plan
        u_IC= Expression("0", t=0, degree=0) # degree=1?
        u_n=interpolate(u_IC,V)

    P=P*scale # Scale P according to previous calculations
#F=dt*alpha*u*v*ds + c*rho*v*u*dx + dt*k_tis*dot(grad(u), grad(v))*dx - (c*rho*u_n + dt*(P-w_c_b*u))*v*dx - T_out_ht*v*ds
    F=dt*alpha*u*v*ds + v*u*dx + dt*k_tis*dot(grad(u), grad(v))*dx - (u_n + dt*(P-w_c_b*u))*v*dx - T_out_ht*v*ds
    #dt*alpha*u*v*ds + v*u*dx + dt*k_tis*dot(grad(u), grad(v))*dx - (u_n + dt*(P-w_c_b*u))*v*dx - T_out_ht*v*ds
    #alpha*u*v*dx + dt*k_tis*dot(grad(u), grad(v))*dx - (u_n + dt*(P-w_c_b*u))*v*dx + T_out_ht*v*ds
    a=lhs(F)
    L=rhs(F)

    u=Function(V)

    # Now take steps in time and estimate the temperature for each time step, until the full scaling is made.
    t=0
    for n in range(int(numSteps)):
        # Update time
        t += dt
        #u_IC.t=t
        
        # Solve the system
        solve(a == L, u, solver_parameters={'linear_solver':'gmres'})   #might need to change from gmres to other solver?
        T =u.vector().array()
        
        
        # Print the highest temperature
        print("Tmax for time step number " + str(int(t/dt)) + ":")
        print(np.max(T))
        print(np.min(T))
        
        u_n.assign(u)
        
        # If okay temperature then save data for each time step in format readable by MATLAB
        if (np.max(T)<Tmax and np.max(T)>Tmin):
            Coords = mesh.coordinates()
            Cells  = mesh.cells()
            
            # Index for this time step should be included in the name for the temperature file
            index=t/dt
            f = h5py.File('../FEniCS_results/temperature_'+ str(i+1)+ str(index) + '.h5','w')
            f.create_dataset(name='Temp', data=T)
            f.create_dataset(name='P',    data=Coords)
            f.create_dataset(name='T',    data=Cells)
            # Need a dof(degree of freedom)-map to permutate Temp
            f.create_dataset(name='Map',  data=dof_to_vertex_map(V))
            f.close()
            print("saved T for step: ")
            print(index)

        # Estimate new matrix for perfusion if non_linear_perfusion=True
        #if non_linear_perfusion
        #   engine.generate_perfusion_nonlin()

    print("Time iteration finished for plan " + str(i+1))

print("All calculations are finished for the given input.")
#-------------------------------------------------------------------------------------------















