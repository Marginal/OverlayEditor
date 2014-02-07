#version 120

attribute float skip;	// would prefer bool, but that requires GLSL 1.30

void main()
{
    gl_Position = gl_ProjectionMatrix * gl_Vertex;
    gl_Position.z += skip * 2 * gl_Position.w;	// send beyond far clipping plane
    gl_FrontColor = gl_Color;
}
