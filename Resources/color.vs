#version 120

void main()
{
    gl_Position = gl_ProjectionMatrix * gl_Vertex;
    gl_FrontColor = gl_Color;
}
